# zeljo-news-bot
Automatic FK Željezničar news: checks Bosnian sports portals every 15 minutes and posts new articles to a Discord channel.

Runs for free on GitHub Actions, with no server, computer or phone needed.

## What it tracks

**Portals:** Klix.ba, SportSport.ba, SCsport.ba, BHFudbal.ba, Sportske.ba, Reprezentacija.ba, MeridianSport.ba, Oslobođenje, SportBC.ba, SportskiPuls.ba, Sport.ba, Avaz.ba and the official FK Željezničar website.

**Topics:** Željezničar (all grammatical cases), Željo, FKŽ, Grbavica, Manijaci, plavo-bijeli, Ivica Osim, Amar Osim, the head coach and any players on the list.

The bot searches the title, link and full article text, so any mention of the club is enough. For portals without RSS, it opens each new article to read its text. If several portals cover the same story, it is posted from each of them (set `DUPLIKATI_PO_NASLOVU = True` to skip identical titles).

## How it works

1. cron-job.org triggers the GitHub Actions workflow every 15 minutes from 07:00 to 23:45 (Sarajevo time), which runs `zeljo-news-bot.py`. Nothing runs at night; night articles are posted in the first morning run.
2. The script reads the portals, via RSS where available and by reading the front page for the rest. SportSport.ba blocks servers (Cloudflare), so it is read through a Google News search of that site, and Google links are converted back to direct SportSport links.
3. Articles that mention the club are posted to Discord through a webhook.
4. Posted articles are saved in `vijesti_vidjene.json`, so they are never repeated.

## Setup

1. **Discord webhook:** right-click the channel → **Edit Channel → Integrations → Webhooks → New Webhook → Copy Webhook URL**.
2. **GitHub secret:** **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `DISCORD_WEBHOOK`
   - Secret: the webhook URL
3. **First run:** **Actions → Vijesti → Run workflow**.

On the first run the bot posts every matching article from the last 24 hours. After that, it posts only new ones.

## Customization

Everything is set at the top of `zeljo-news-bot.py` (open the file on GitHub → ✏️ → **Commit changes**):

| What | Where |
|---|---|
| Portals | `IZVORI` |
| Club-related keywords | `KLUB` |
| Players, coaches, staff | `LJUDI` (always first + last name, e.g. `"sulejman* krpic*"`) |
| Maximum article age | `MAX_STAROST_SATI` |
| How many text mentions are needed | `TEKST_MIN_SPOMINJANJA` |
| How far back the first run looks | `PRVI_PUT_SATI` |
| How often and when it checks | the cronjob schedule on cron-job.org |

A `*` at the end of a word means "any ending" (`grbavic*` matches Grbavica, Grbavici, Grbavicu…). Diacritics and capitalization don't matter.

## Checking that it works

Every run is listed under **Actions**. Open a run → **objavi** → **Provjeri portale i objavi** to see how many articles were found on each portal:

```
Izvori: Klix.ba 40 · SportSport.ba 25 · Avaz.ba 30 · ...
```

If a portal keeps showing `0` or ⚠️, its page structure has probably changed and its address in `IZVORI` needs updating.

## Notes

- The bot posts only the title and link and never copies article text.
- The webhook URL is a secret, so keep it only in GitHub Secrets.
