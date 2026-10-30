# Nyrix plugin sources

Sources for plugins built for Nyrix SMP. Compile against the server's own
`libraries/io/papermc/paper/paper-api/1.21.11-R0.1-SNAPSHOT/*.jar`, plus adventure, gson,
bungeecord-chat and Vault from Maven Central (`--release 21`).

- **NyrixUpdateLog**: after a restart, posts changed plugin jars + `plugins/NyrixUpdateLog/notes.txt` to Discord `#updates`.
- **NyrixInvestigate**: `/sus investigate <case-id>` for the investigator who claimed a case (reads `plugins/NyrixClaims/claims.json`), plus a private Discord DM with the command. `tests/T.java` holds the offline logic tests.

No secrets are stored here; both plugins read the bot token from `NyrixDiscord/config.yml` or the `DISCORD_BOT_TOKEN` environment variable.
