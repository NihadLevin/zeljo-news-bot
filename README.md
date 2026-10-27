# zeljo-news-bot
Automatic FK Željezničar news: checks Bosnian sports portals every 15 minutes and posts new articles to a Discord channel.

Runs for free on GitHub Actions, with no server, computer or phone needed.

## What it tracks

**Portals:** Klix.ba, SportSport.ba, SCsport.ba, BHFudbal.ba, Sportske.ba, Reprezentacija.ba, MeridianSport.ba, Oslobođenje, SportBC.ba, SportskiPuls.ba, Sport.ba, Avaz.ba and the official FK Željezničar website.

**Topics:** Željezničar (all grammatical cases), Željo, FKŽ, Grbavica, Manijaci, plavo-bijeli, Ivica Osim, Amar Osim, the head coach and any players on the list.

For portals with an RSS feed, the bot searches the title, link and article intro. For the others, it searches the title and link. If the same article appears on several portals, it is posted only once.

## How it works

1. GitHub Actions runs `vijesti.py` every 15 minutes.
2. The script reads the portals, via RSS where available and by reading the front page for the rest.
3. Articles that mention the club are posted to Discord through a webhook.
4. Posted articles are saved in `vijesti_vidjene.json`, so they are never repeated.

## Setup

1. **Discord webhook:** right-click the channel → **Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**.
2. **GitHub secret:** **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `DISCORD_WEBHOOK`
   - Secret: the webhook URL
3. **First run:** **Actions → Vijesti → Run workflow**.

On the first run the bot posts up to 3 of the latest articles. After that, it posts only new ones.

## Customization

Everything is set at the top of `vijesti.py` (open the file on GitHub → ✏️ → **Commit changes**):

| What | Where |
|---|---|
| Portals | `IZVORI` |
| Club-related keywords | `KLUB` |
| Players, coaches, staff | `LJUDI` (always first + last name, e.g. `"sulejman* krpic*"`) |
| Maximum article age | `MAX_STAROST_SATI` |
| How often it checks | `cron` in `.github/workflows/vijesti.yml` |

A `*` at the end of a word means "any ending" (`grbavic*` matches Grbavica, Grbavici, Grbavicu…). Diacritics and capitalization don't matter.

## Checking that it works

Every run is listed under **Actions**. Open a run → **objavi** → **Provjeri portale i objavi** to see how many articles were found on each portal:

```
Izvori: Klix.ba 40 · SportSport.ba 25 · Avaz.ba 30 · ...
```

If a portal keeps showing `0` or ⚠️, its page structure has probably changed and its address in `IZVORI` needs updating.

## Notes

- GitHub scheduled runs can be delayed by 5–15 minutes, which is normal.
- The bot posts only the title and link and never copies article text.
- The webhook URL is a secret, so keep it only in GitHub Secrets.
