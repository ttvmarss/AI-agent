package dev.nyrix.updatelog;

import java.io.File;
import java.io.InputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.plugin.java.JavaPlugin;

public final class NyrixUpdateLog extends JavaPlugin {
    private static final Pattern BASE = Pattern.compile("^(.*?)[-_ ]v?\\d.*\\.jar$", Pattern.CASE_INSENSITIVE);

    @Override
    public void onEnable() {
        saveDefaultConfig();
        long delay = Math.max(5, getConfig().getLong("delay-seconds", 20)) * 20L;
        getServer().getScheduler().runTaskLaterAsynchronously(this, this::run, delay);
    }

    private static final class Jar {
        final String file; final String sha;
        Jar(String file, String sha) { this.file = file; this.sha = sha; }
    }

    private String baseName(String file) {
        Matcher m = BASE.matcher(file);
        String b = m.matches() ? m.group(1) : file.substring(0, file.length() - 4);
        return b;
    }

    private Map<String, Jar> scan() throws Exception {
        Map<String, Jar> out = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        File dir = getDataFolder().getParentFile();
        List<String> ignore = new ArrayList<>();
        for (String s : getConfig().getStringList("ignore")) ignore.add(s.toLowerCase(Locale.ROOT));
        File[] files = dir.listFiles((d, n) -> n.toLowerCase(Locale.ROOT).endsWith(".jar"));
        if (files == null) return out;
        for (File f : files) {
            String base = baseName(f.getName());
            if (ignore.contains(base.toLowerCase(Locale.ROOT))) continue;
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            try (InputStream in = Files.newInputStream(f.toPath())) {
                byte[] buf = new byte[65536]; int n;
                while ((n = in.read(buf)) > 0) md.update(buf, 0, n);
            }
            StringBuilder sb = new StringBuilder();
            for (byte b : md.digest()) sb.append(String.format("%02x", b));
            out.put(base, new Jar(f.getName(), sb.toString()));
        }
        return out;
    }

    private void run() {
        try {
            getDataFolder().mkdirs();
            Map<String, Jar> now = scan();
            File snap = new File(getDataFolder(), "snapshot.properties");
            File notesFile = new File(getDataFolder(), "notes.txt");
            Properties old = new Properties();
            boolean first = !snap.exists();
            if (!first) try (InputStream in = Files.newInputStream(snap.toPath())) { old.load(in); }

            List<String> added = new ArrayList<>(), updated = new ArrayList<>(), removed = new ArrayList<>();
            if (!first) {
                for (Map.Entry<String, Jar> e : now.entrySet()) {
                    String prev = old.getProperty(e.getKey());
                    if (prev == null) { added.add("**" + e.getKey() + "** (" + e.getValue().file + ")"); continue; }
                    String[] p = prev.split("\\|", 2);
                    if (!p[1].equals(e.getValue().sha))
                        updated.add("**" + e.getKey() + "**: " + p[0] + " → " + e.getValue().file);
                }
                for (String k : old.stringPropertyNames())
                    if (!now.containsKey(k)) removed.add("**" + k + "** (" + old.getProperty(k).split("\\|", 2)[0] + ")");
            }
            String notes = notesFile.exists() ? Files.readString(notesFile.toPath()).trim() : "";
            boolean changed = !added.isEmpty() || !updated.isEmpty() || !removed.isEmpty();

            if (changed || !notes.isEmpty()) {
                StringBuilder d = new StringBuilder();
                if (!notes.isEmpty()) d.append("**What changed**\n").append(notes).append("\n\n");
                if (first) d.append("_Update tracking started; plugin file changes are listed from the next update on._");
                section(d, "Updated", updated); section(d, "Added", added); section(d, "Removed", removed);
                if (post(d.toString().trim())) {
                    if (!notes.isEmpty()) {
                        File hist = new File(getDataFolder(), "notes-history");
                        hist.mkdirs();
                        Files.move(notesFile.toPath(), new File(hist, "notes-" + Instant.now().getEpochSecond() + ".txt").toPath(), StandardCopyOption.REPLACE_EXISTING);
                    }
                    save(snap, now);
                } else {
                    getLogger().warning("Could not post the update log; will retry on next start.");
                }
            } else {
                save(snap, now);
            }
        } catch (Exception e) {
            getLogger().warning("Update log failed: " + e);
        }
    }

    private void section(StringBuilder d, String title, List<String> items) {
        if (items.isEmpty()) return;
        d.append("**").append(title).append("**\n");
        for (String s : items) d.append("• ").append(s).append('\n');
        d.append('\n');
    }

    private void save(File snap, Map<String, Jar> now) throws Exception {
        Properties p = new Properties();
        for (Map.Entry<String, Jar> e : now.entrySet()) p.setProperty(e.getKey(), e.getValue().file + "|" + e.getValue().sha);
        try (var out = Files.newOutputStream(snap.toPath())) { p.store(out, "NyrixUpdateLog snapshot"); }
    }

    private String token() {
        String t = getConfig().getString("bot-token", "");
        if (t != null && !t.isBlank()) return t.trim();
        File f = new File(getDataFolder().getParentFile(), "NyrixDiscord/config.yml");
        if (f.exists()) {
            t = YamlConfiguration.loadConfiguration(f).getString("bot-token", "");
            if (t != null && !t.isBlank()) return t.trim();
        }
        t = System.getenv("DISCORD_BOT_TOKEN");
        return t == null ? "" : t.trim();
    }

    private static String esc(String s) {
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': break;
                case '\t': b.append("  "); break;
                default: if (c < 0x20) b.append(' '); else b.append(c);
            }
        }
        return b.toString();
    }

    private boolean post(String description) throws Exception {
        String token = token();
        String channel = getConfig().getString("channel-id", "");
        if (token.isEmpty() || channel.isBlank()) { getLogger().warning("No bot token or channel-id configured."); return false; }
        if (description.length() > 3900) description = description.substring(0, 3900) + "\n…";
        String body = "{\"embeds\":[{\"title\":\"Server updated\",\"color\":5763719,\"description\":\"" + esc(description)
                + "\",\"footer\":{\"text\":\"NYRIX SMP | auto update log\"},\"timestamp\":\"" + Instant.now() + "\"}],\"allowed_mentions\":{\"parse\":[]}}";
        HttpRequest req = HttpRequest.newBuilder(URI.create("https://discord.com/api/v10/channels/" + channel + "/messages"))
                .header("Authorization", "Bot " + token).header("Content-Type", "application/json")
                .header("User-Agent", "DiscordBot (NyrixUpdateLog, 1.0.0)")
                .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8)).build();
        HttpResponse<String> r = HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString());
        if (r.statusCode() / 100 == 2) { getLogger().info("Posted update log to Discord."); return true; }
        getLogger().warning("Discord returned HTTP " + r.statusCode());
        return false;
    }
}
