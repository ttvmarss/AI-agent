package dev.nyrix.investigate;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.reflect.TypeToken;
import java.io.File;
import java.lang.reflect.Type;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import net.kyori.adventure.text.serializer.legacy.LegacyComponentSerializer;
import org.bukkit.Bukkit;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.player.PlayerCommandPreprocessEvent;
import org.bukkit.plugin.java.JavaPlugin;

public final class NyrixInvestigate extends JavaPlugin implements Listener {
    private static final Gson GSON = new Gson();
    private static final Type CASES = new TypeToken<LinkedHashMap<String, Case>>() {}.getType();
    private static final Type NOTIFIED = new TypeToken<HashSet<String>>() {}.getType();
    private static final LegacyComponentSerializer LEGACY = LegacyComponentSerializer.legacyAmpersand();
    private static final Pattern CMD = Pattern.compile("^/(?:[a-z0-9_]+:)?(?:sus|suspects)\\s+investigate(?:\\s+(\\S+))?\\s*$", Pattern.CASE_INSENSITIVE);
    private final HttpClient http = HttpClient.newHttpClient();
    private final Set<String> notified = new HashSet<>();
    private boolean seeded;

    public static final class Case {
        public String id, uuid, name, status, claimerUuid, claimerName, claimerDiscord;
        public long claimedAt;
    }

    public enum Verdict { OK, NO_CASE, NOT_CLAIMED, CLOSED, NOT_YOURS }

    /** Pure decision logic: who may start an investigation on this case. */
    public static Verdict decide(Case c, UUID player, UUID owner) {
        if (c == null) return Verdict.NO_CASE;
        String st = c.status == null ? "" : c.status;
        if (st.equals("CLEARED") || st.equals("CONFIRMED") || st.equals("CLOSED")) return Verdict.CLOSED;
        if (owner != null && owner.equals(player)) return st.equals("UNDER_INVESTIGATION") || st.equals("UNCLAIMED") ? Verdict.OK : Verdict.CLOSED;
        if (!st.equals("UNDER_INVESTIGATION") || c.claimerUuid == null) return Verdict.NOT_CLAIMED;
        return c.claimerUuid.equals(player.toString()) ? Verdict.OK : Verdict.NOT_YOURS;
    }

    /** Returns the case id from a "/sus investigate <id>" line, "" when the id is missing, null when it isn't this command. */
    public static String parse(String message) {
        Matcher m = CMD.matcher(message.trim());
        if (!m.matches()) return null;
        return m.group(1) == null ? "" : m.group(1);
    }

    @Override
    public void onEnable() {
        saveDefaultConfig();
        getDataFolder().mkdirs();
        File nf = new File(getDataFolder(), "notified.json");
        try {
            if (nf.exists()) { Set<String> s = GSON.fromJson(Files.readString(nf.toPath()), NOTIFIED); if (s != null) { notified.addAll(s); seeded = true; } }
        } catch (Exception e) { getLogger().warning("notified.json unreadable: " + e); }
        getServer().getPluginManager().registerEvents(this, this);
        long ticks = Math.max(2, getConfig().getLong("poll-seconds", 5)) * 20L;
        getServer().getScheduler().runTaskTimerAsynchronously(this, this::poll, 100L, ticks);
        getLogger().info("NyrixInvestigate enabled: /sus investigate <case-id>");
    }

    private Map<String, Case> cases() {
        try {
            File f = new File(getDataFolder().getParentFile(), "NyrixClaims/claims.json");
            if (!f.exists()) return new LinkedHashMap<>();
            Map<String, Case> m = GSON.fromJson(Files.readString(f.toPath()), CASES);
            return m == null ? new LinkedHashMap<>() : m;
        } catch (Exception e) { return null; }
    }

    private UUID owner() {
        try {
            YamlConfiguration y = YamlConfiguration.loadConfiguration(new File(getDataFolder().getParentFile(), "NyrixClaims/config.yml"));
            String u = y.getString("owner.mc-uuid", "");
            if (u != null && !u.isBlank()) return UUID.fromString(u.trim());
            return Bukkit.getOfflinePlayer(y.getString("owner.mc-name", "Nyrix")).getUniqueId();
        } catch (Exception e) { return null; }
    }

    private String msg(String key, String... kv) {
        String s = getConfig().getString("messages." + key, key);
        for (int i = 0; i + 1 < kv.length; i += 2) s = s.replace("%" + kv[i] + "%", kv[i + 1]);
        return getConfig().getString("messages.prefix", "") + s;
    }

    private void say(Player p, String s) { p.sendMessage(LEGACY.deserialize(s)); }

    @EventHandler(priority = EventPriority.LOWEST, ignoreCancelled = true)
    public void onCommand(PlayerCommandPreprocessEvent e) {
        String id = parse(e.getMessage());
        if (id == null) return;
        e.setCancelled(true);
        Player p = e.getPlayer();
        if (id.isEmpty()) { say(p, msg("usage")); return; }
        Map<String, Case> all = cases();
        Case c = all == null ? null : all.get(id.toUpperCase());
        Verdict v = decide(c, p.getUniqueId(), owner());
        switch (v) {
            case NO_CASE -> { say(p, msg("no-case")); audit("investigate_denied", id, p.getName(), "no such case"); }
            case NOT_CLAIMED -> { say(p, msg("not-claimed")); audit("investigate_denied", id, p.getName(), "case not claimed"); }
            case CLOSED -> { say(p, msg("closed")); }
            case NOT_YOURS -> { say(p, msg("not-yours", "staff", String.valueOf(c.claimerName))); audit("investigate_denied", c.id, p.getName(), "not the investigator (" + c.claimerName + ")"); }
            case OK -> {
                Player target = c.uuid == null ? null : Bukkit.getPlayer(UUID.fromString(c.uuid));
                if (target == null && c.name != null) target = Bukkit.getPlayerExact(c.name);
                if (target == null) { say(p, msg("offline")); audit("investigate_offline", c.id, p.getName(), "target " + c.name + " offline"); return; }
                say(p, msg("starting", "player", target.getName()));
                audit("investigate_started", c.id, p.getName(), "target " + target.getName());
                final String run = "sus " + target.getName();
                Bukkit.getScheduler().runTask(this, () -> p.performCommand(run));
            }
        }
    }

    private void poll() {
        try {
            if (!getConfig().getBoolean("dm-on-claim", true)) return;
            Map<String, Case> all = cases();
            if (all == null) return;
            boolean changed = false;
            for (Case c : all.values()) {
                if (!"UNDER_INVESTIGATION".equals(c.status) || c.claimerDiscord == null || c.claimerDiscord.isBlank()) continue;
                String key = c.id + ":" + c.claimerUuid + ":" + c.claimedAt;
                if (notified.contains(key)) continue;
                notified.add(key); changed = true;
                if (!seeded) continue; // first ever start: don't DM claims that predate this plugin
                dm(c);
            }
            seeded = true;
            if (changed || !new File(getDataFolder(), "notified.json").exists())
                Files.writeString(new File(getDataFolder(), "notified.json").toPath(), GSON.toJson(notified), StandardCharsets.UTF_8);
        } catch (Exception e) { getLogger().warning("poll failed: " + e); }
    }

    private String token() {
        String t = getConfig().getString("bot-token", "");
        if (t != null && !t.isBlank()) return t.trim();
        File f = new File(getDataFolder().getParentFile(), "NyrixDiscord/config.yml");
        if (f.exists()) { t = YamlConfiguration.loadConfiguration(f).getString("bot-token", ""); if (t != null && !t.isBlank()) return t.trim(); }
        t = System.getenv("DISCORD_BOT_TOKEN");
        return t == null ? "" : t.trim();
    }

    private String rest(String path, String json) throws Exception {
        HttpRequest r = HttpRequest.newBuilder(URI.create("https://discord.com/api/v10" + path))
                .header("Authorization", "Bot " + token()).header("Content-Type", "application/json")
                .header("User-Agent", "DiscordBot (NyrixInvestigate, 1.0.0)")
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8)).build();
        HttpResponse<String> resp = http.send(r, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() / 100 != 2) throw new IllegalStateException("Discord HTTP " + resp.statusCode());
        return resp.body();
    }

    private void dm(Case c) {
        try {
            JsonObject req = new JsonObject(); req.addProperty("recipient_id", c.claimerDiscord);
            String ch = GSON.fromJson(rest("/users/@me/channels", req.toString()), JsonObject.class).get("id").getAsString();
            JsonObject m = new JsonObject();
            m.addProperty("content", "**You claimed case " + c.id + " (" + c.name + ").** Copy this into Minecraft chat:\n```\n/sus investigate " + c.id + "\n```\nWhen you're done, exit with:\n```\n/sus stop\n```\nOnly you (and the owner) can use this case's command.");
            JsonObject am = new JsonObject(); am.add("parse", new com.google.gson.JsonArray()); m.add("allowed_mentions", am);
            rest("/channels/" + ch + "/messages", m.toString());
            audit("investigate_command_sent", c.id, String.valueOf(c.claimerName), "private DM sent");
        } catch (Exception e) { getLogger().warning("Could not DM investigator for " + c.id + ": " + e.getMessage()); }
    }

    private void audit(String kind, String caseId, String who, String note) {
        getLogger().info("[audit] " + kind + " case=" + caseId + " by=" + who + " " + note);
        Bukkit.getScheduler().runTaskAsynchronously(this, () -> {
            try {
                YamlConfiguration y = YamlConfiguration.loadConfiguration(new File(getDataFolder().getParentFile(), "NyrixClaims/config.yml"));
                String ch = y.getString("channels.audit", "");
                if (ch == null || ch.isBlank()) return;
                JsonObject m = new JsonObject();
                m.addProperty("content", "🔎 `" + kind + "` case **" + caseId + "** · " + who + " · " + note);
                JsonObject am = new JsonObject(); am.add("parse", new com.google.gson.JsonArray()); m.add("allowed_mentions", am);
                rest("/channels/" + ch + "/messages", m.toString());
            } catch (Exception ignored) { }
        });
    }
}
