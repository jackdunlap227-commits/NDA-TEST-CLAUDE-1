# Unifi NDA Reviewer (Microsoft Teams agent)

A Teams bot that reviews buy-side M&A NDAs against the **Unifi M&A NDA Playbook** and gives back a
Word redline.

1. In a 1:1 chat with the bot, attach the NDA (`.docx`) and press send. You can add notes in the
   same message, for example `second turn` or `Target is Acme Corp`.
2. Claude reads the NDA clause by clause against every playbook rule
   ([`playbooks/Unifi - MA NDA Playbook.docx`](playbooks/)).
3. The bot replies with a summary and action items (such as "clear with Jessica" or "clear with
   the business") and a file card. Click **Allow** and the redlined `.docx` is saved to the chat.

The redline uses real **Word tracked changes**, so deletions show as strikethroughs and insertions
as underlined text. Anyone can accept or reject each change in Word (Review → Accept/Reject). Each
change has a margin comment that names the playbook rule behind it and, where the playbook gives
one, the fallback position for the next turn.

## How it works

```
Teams ──file──▶ app.py (/api/messages, M365 Agents SDK)
                   │  nda_agent/teams_bot.py   download upload, reply right away, run in background
                   ▼
              nda_agent/pipeline.py
                   ├─ redline.py   number every paragraph [p0], [p1] … (skips text already deleted)
                   ├─ reviewer.py  Claude + playbook (prompt-cached) → JSON edits
                   │                {paragraph, replace|insert|insert_paragraph_after, text, rule, comment}
                   └─ redline.py   apply each edit as <w:del>/<w:ins> + comment, turn on Track Changes
                   ▼
Teams ◀── summary + file consent card ──▶ upload the redline to the user's OneDrive
```

* **Review turns:** the first turn takes the playbook's preferred position. If you type
  `second turn` with the counterparty's markup, the bot applies the "Standard Fallback" column:
  it accepts what the playbook allows on the second turn and keeps pushing on items that are
  non-negotiable, such as the waiver of consequential damages.
* **Robust matching:** edits are matched even when the text is split across differently
  formatted runs, or when it uses curly quotes or non-breaking spaces. If an edit can't be
  placed, it is never silently dropped. It becomes a margin comment, and the chat summary lists
  it under "Needs manual edit".
* **Changing the playbook:** replace the `.docx` in `playbooks/` (or set `PLAYBOOK_PATH`). It can
  be any table of topic / issue / fallback rows, or a `.md`/`.txt` file.

## Run it locally (no Teams)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set ANTHROPIC_API_KEY
python samples/make_sample_nda.py
python -m nda_agent.cli "samples/Sample Target NDA.docx"            # first turn
python -m nda_agent.cli their-markup.docx --turn second --note "Target is Acme"
pytest                                                              # tests run offline
```

## Deploy to Microsoft Teams

You need an Azure subscription, permission to create an Entra app registration, and a Teams
admin, or a tenant that allows custom app upload.

1. **Host the web app.** Build the Docker image and run it on Azure App Service or Azure
   Container Apps. Any HTTPS host works. Set the variables from `.env.example` as app settings.
   Keep a single instance, or move `PendingFiles` in `teams_bot.py` to Blob storage first.
   On App Service, turn on **Always On**, because reviews keep running after the HTTP request
   returns.
   ```bash
   docker build -t nda-reviewer .
   ```
   For local testing with Teams, use a dev tunnel instead:
   `devtunnel host -p 3978 --allow-anonymous`.
2. **Create an Azure Bot** resource (single tenant). Under *Configuration*:
   * Messaging endpoint: `https://<your-host>/api/messages`
   * Note the **Microsoft App ID**. Create a **client secret** on that app registration
     (*Manage Password*). Put the app ID, secret and tenant ID into the
     `CONNECTIONS__SERVICE_CONNECTION__SETTINGS__*` variables.
   * Under *Channels*, add **Microsoft Teams**.
3. **Build the Teams app package:**
   ```bash
   python appPackage/build_package.py <Microsoft App ID>
   ```
   Then upload `appPackage/nda-reviewer.zip`. Either use Teams → *Apps* → *Manage your apps* →
   *Upload an app*, or have an admin publish it in the Teams admin center so the legal team can
   find it.
4. Open the bot in Teams, attach an NDA, and send.

`supportsFiles` is enabled in the manifest. Teams supports file upload and download for bots only
in **personal (1:1) chats**, so the app is scoped to personal chat.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Claude API key |
| `NDA_MODEL` | `claude-opus-5-5` | Model used for the review |
| `NDA_EFFORT` | `high` | Reasoning effort (`medium` is faster and cheaper; `xhigh` is more thorough) |
| `REDLINE_AUTHOR` / `REDLINE_INITIALS` | `Unifi Legal` / `UL` | Name on the tracked changes and comments |
| `ADD_COMMENTS` | `true` | Add playbook-rationale comments. Set to `false` before sending a redline straight to the counterparty, or delete the comments in Word. |
| `PLAYBOOK_PATH` | bundled playbook | Use a different playbook |
| `MAX_UPLOAD_MB` | `15` | Upload size limit |

## Notes and limits

* Only `.docx` files are supported, because tracked changes need a Word file. For a PDF, open it
  in Word, save it as `.docx`, and resend it.
* Edits are made in the document body, including tables. Headers, footers and footnotes are not
  edited.
* The comments are internal reasoning. Review them before you send the redline externally.
* A lawyer should review the redline before it goes out. The bot flags items that need clearance
  (Target name, entity, consent to financing sources, and so on) in the chat summary.
