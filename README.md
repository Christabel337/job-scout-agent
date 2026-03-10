#  Job Scout Agent
### Autonomous Job Hunting Agent · Built with Hermes Agent · Nous Research Hackathon

> *One command. Real jobs. Automatic tracking. Every time.*

#  What It Does

Job Scout is a fully autonomous agent that does your entire job search for you:

-  **Fetches real jobs** from multiple live job board APIs
-  **Scores every listing** against your skills and preferences
-  **Researches each company** automatically
-  **Saves everything** into organized folders
-  **Updates a CSV tracker** you can import into Google Sheets
-  **Prints a clean summary** with apply links and scores

Zero manual effort after setup. Just run it and apply.

---

# Built with Hermes Agent

This entire tool was built autonomously by Hermes Agent: it wrote the code, created the files, and tested everything itself.

```
hermes "Build a complete autonomous job hunting tool called Job Scout..."
```

Hermes used these capabilities to build it:
- `execute_code` — wrote and ran Python scripts
- `write_file` — created all project files
- `browser` — fetched real job data from APIs

---

#  How To Use It

### 1. Install Hermes Agent
```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

## 2. Edit your profile
Open `profile.conf` and fill in your details:
```ini
- name — your name or job title description
- target_title — the job titles you are looking for
- target_skills — your technical skills
- experience_years — how many years of experience you have
- location_preference — *Remote Only* or your city
- salary_expectation — your minimum salary in USD
- work_authorization — your work status
- relocation — whether you are open to relocating
```

## 3. Run Job Scout
```bash
python3 job_scout.py
```

---

# 📂 Output Structure

```
~/job_scout_results/
  2026-03-10/
    summary.md                    ← Daily report
    Anduril_SoftwareEngineer/
      job_description.txt         ← Clean job details
      match_score.txt             ← Score: 88/100
      apply_link.txt              ← Real application URL
      company_research.txt        ← Company info
  job_scout_tracker.csv           ← Import into Google Sheets
```

---

## Google Sheets Tracker

Every run automatically updates `job_scout_tracker.csv` with:

| Date Found | Job Title | Company | Score | Salary | Remote | Apply Link | Status | Follow Up |
|---|---|---|---|---|---|---|---|---|
| 2026-03-10 | Software Engineer | Stripe | 88/100 | $150k | Yes | link | Not Applied | 2026-03-17 |

**Import it:** Google Sheets → File → Import → Upload `job_scout_tracker.csv`

# 👤 Built By
**Christabel** · [@Christabel556](https://twitter.com/Christabel556)
