#!/usr/bin/env python3
"""
Job Scout - Autonomous Job Hunting Tool
No external dependencies version - uses only standard library.
"""

import os
import sys
import json
import csv
import re
import time
import configparser
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote
import subprocess
import html
import urllib.request
import urllib.error
import ssl
from html.parser import HTMLParser

# Configuration
CONFIG_FILE = "profile.conf"
RESULTS_DIR = os.path.expanduser("~/job_scout_results")
CSV_FILENAME = "job_scout_tracker.csv"

# Default browser-like headers to avoid 403 blocks
DEFAULT_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'identity',  # Disable compression so we get plain text back
    'Connection': 'keep-alive',
    'Cache-Control': 'no-cache',
}

class HTMLStripper(HTMLParser):
    """Simple HTML tag stripper"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    
    def handle_data(self, d):
        self.text.append(d)
    
    def get_data(self):
        return ''.join(self.text)

def strip_html_tags(text):
    """Strip HTML tags from text"""
    if not text:
        return ""
    text = html.unescape(text)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<li\s*>', '\n• ', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()

def fetch_json(url, extra_headers=None, retries=3, backoff=2):
    """
    Fetch JSON from URL.
    - Merges DEFAULT_HEADERS with any extra_headers provided.
    - Retries on transient errors (5xx, timeout).
    - Returns parsed JSON or None on failure.
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    headers = {**DEFAULT_HEADERS, **(extra_headers or {})}

    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
                raw = response.read()
                charset = response.info().get_content_charset('utf-8')
                return json.loads(raw.decode(charset))

        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code} error fetching {url}: {e.reason}")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = backoff ** attempt
                print(f"  Retrying in {wait}s... (attempt {attempt}/{retries})")
                time.sleep(wait)
            else:
                return None

        except urllib.error.URLError as e:
            print(f"  URL error fetching {url}: {e.reason}")
            if attempt < retries:
                time.sleep(backoff ** attempt)
            else:
                return None

        except Exception as e:
            print(f"  Unexpected error fetching {url}: {e}")
            return None

    return None


class JobScout:
    def __init__(self):
        """Initialize Job Scout with configuration"""
        self.config = self.load_config()
        self.jobs = []
        self.scored_jobs = []
        self.today = datetime.now().strftime("%Y-%m-%d")
        
        self.today_dir = os.path.join(RESULTS_DIR, self.today)
        os.makedirs(self.today_dir, exist_ok=True)
        
        self.target_titles = [t.strip().lower() for t in 
                             self.config.get('user', 'target_title').split(',')]
        self.target_skills = [s.strip().lower() for s in 
                             self.config.get('user', 'target_skills').split(',')]
        self.require_remote = self.config.getboolean('preferences', 'require_remote')
        self.min_salary = self.config.getint('preferences', 'min_salary')
        
        self.weights = {
            'title': self.config.getint('scoring', 'weight_title_match'),
            'skills': self.config.getint('scoring', 'weight_skills_match'),
            'remote': self.config.getint('scoring', 'weight_remote'),
            'salary': self.config.getint('scoring', 'weight_salary'),
            'company_size': self.config.getint('scoring', 'weight_company_size'),
            'industry': self.config.getint('scoring', 'weight_industry')
        }
        
        if sum(self.weights.values()) != 100:
            print(f"Warning: Scoring weights sum to {sum(self.weights.values())}, not 100")
    
    def load_config(self):
        """Load configuration from profile.conf"""
        config = configparser.RawConfigParser()
        
        config['user'] = {
            'name': 'Full-Stack Python React Developer',
            'target_title': 'Senior Software Engineer, Full Stack Developer, Software Engineer, Backend Engineer, Frontend Engineer',
            'target_skills': 'python, django, flask, fastapi, react, javascript, typescript, node.js, postgresql, mongodb, aws, docker, kubernetes, git, ci/cd, rest api, graphql',
            'experience_years': '5',
            'location_preference': 'Remote Only',
            'salary_expectation': '130000 USD',
            'work_authorization': 'US Citizen',
            'relocation': 'No'
        }
        
        config['scoring'] = {
            'weight_title_match': '25',
            'weight_skills_match': '30',
            'weight_remote': '20',
            'weight_salary': '15',
            'weight_company_size': '5',
            'weight_industry': '5'
        }
        
        config['apis'] = {
            # Added &limit=50 and switched to https with explicit format
            'remotive_url': 'https://remotive.com/api/remote-jobs?category=software-dev&limit=50',
            # Arbeitnow supports a ?page= param; start at page 1
            'arbeitnow_url': 'https://arbeitnow.com/api/job-board-api?page=1',
            'remoteok_url': 'https://remoteok.com/api',
            # The Muse: use api_key param placeholder (leave empty for anonymous)
            'themuse_url': 'https://www.themuse.com/api/public/jobs?category=Software%%20Engineer&level=Mid%%20Level&page=1'
        }
        
        config['preferences'] = {
            'max_jobs_per_api': '50',
            'min_salary': '80000',
            'require_remote': 'true',
            'blacklist_companies': '',
            'whitelist_industries': 'Technology, SaaS, Fintech, Healthcare, E-commerce'
        }
        
        config['output'] = {
            'results_dir': '~/job_scout_results',
            'save_individual_folders': 'true',
            'create_csv_tracker': 'true',
            'csv_filename': 'job_scout_tracker.csv',
            'research_companies': 'true'
        }
        
        if os.path.exists(CONFIG_FILE):
            config.read(CONFIG_FILE)
            print(f"Loaded configuration from {CONFIG_FILE}")
        else:
            print(f"Created default configuration. Please edit {CONFIG_FILE}")
            with open(CONFIG_FILE, 'w') as f:
                config.write(f)
        
        return config
    
    # ------------------------------------------------------------------
    # API Fetchers — each passes the headers most likely to succeed
    # ------------------------------------------------------------------

    def fetch_remotive_jobs(self):
        """Fetch jobs from Remotive API"""
        url = self.config.get('apis', 'remotive_url')
        print(f"Fetching jobs from Remotive API: {url}")
        
        # Remotive requires Referer to avoid 403
        extra = {'Referer': 'https://remotive.com/'}
        data = fetch_json(url, extra_headers=extra)
        if not data:
            print("  Remotive: no data returned (API may be temporarily unavailable).")
            return
        
        jobs = data.get('jobs', [])
        print(f"  Found {len(jobs)} jobs")
        
        for job in jobs:
            self.jobs.append({
                'source': 'remotive',
                'id': job.get('id'),
                'title': job.get('title', '').strip(),
                'company': job.get('company_name', '').strip(),
                'description': strip_html_tags(job.get('description', '')),
                'url': job.get('url', ''),
                'remote': True,
                'salary': job.get('salary', ''),
                'location': job.get('candidate_required_location', ''),
                'tags': job.get('tags', []),
                'published_date': job.get('publication_date', '')
            })
    
    def fetch_arbeitnow_jobs(self):
        """Fetch jobs from Arbeitnow API"""
        url = self.config.get('apis', 'arbeitnow_url')
        print(f"Fetching jobs from Arbeitnow API: {url}")
        
        # Arbeitnow blocks plain script requests — supply Referer + Origin
        extra = {
            'Referer': 'https://arbeitnow.com/',
            'Origin': 'https://arbeitnow.com',
        }
        data = fetch_json(url, extra_headers=extra)
        if not data:
            print("  Arbeitnow: no data returned (API may require authentication).")
            return
        
        jobs = data.get('data', [])
        print(f"  Found {len(jobs)} jobs")
        
        for job in jobs:
            tags = job.get('tags', [])
            self.jobs.append({
                'source': 'arbeitnow',
                'id': job.get('slug', ''),
                'title': job.get('title', '').strip(),
                'company': job.get('company_name', '').strip(),
                'description': strip_html_tags(job.get('description', '')),
                'url': job.get('url', ''),
                'remote': job.get('remote', False) or 'remote' in [t.lower() for t in tags],
                'salary': job.get('salary', ''),
                'location': job.get('location', ''),
                'tags': tags,
                'published_date': job.get('created_at', '')
            })
    
    def fetch_remoteok_jobs(self):
        """Fetch jobs from RemoteOK API"""
        url = self.config.get('apis', 'remoteok_url')
        print(f"Fetching jobs from RemoteOK API: {url}")
        
        # RemoteOK specifically needs a custom User-Agent & Referer
        extra = {
            'User-Agent': 'Mozilla/5.0 (compatible; JobScout/1.0)',
            'Referer': 'https://remoteok.com/',
        }
        data = fetch_json(url, extra_headers=extra)
        if not data:
            print("  RemoteOK: no data returned.")
            return
        
        jobs = data[1:] if isinstance(data, list) else []
        print(f"  Found {len(jobs)} jobs")
        
        for job in jobs:
            self.jobs.append({
                'source': 'remoteok',
                'id': job.get('id', ''),
                'title': job.get('position', '').strip(),
                'company': job.get('company', '').strip(),
                'description': strip_html_tags(job.get('description', '')),
                'url': job.get('url', ''),
                'remote': True,
                'salary': job.get('salary', ''),
                'location': job.get('location', ''),
                'tags': job.get('tags', []),
                'published_date': job.get('date', '')
            })
    
    def fetch_themuse_jobs(self):
        """Fetch jobs from The Muse API"""
        url = self.config.get('apis', 'themuse_url')
        print(f"Fetching jobs from The Muse API: {url}")
        
        extra = {'Referer': 'https://www.themuse.com/'}
        data = fetch_json(url, extra_headers=extra)
        if not data:
            print("  The Muse: no data returned (try adding an API key to the URL).")
            return
        
        jobs = data.get('results', [])
        print(f"  Found {len(jobs)} jobs")
        
        for job in jobs:
            self.jobs.append({
                'source': 'themuse',
                'id': job.get('id', ''),
                'title': job.get('name', '').strip(),
                'company': job.get('company', {}).get('name', '').strip(),
                'description': strip_html_tags(job.get('contents', '')),
                'url': job.get('refs', {}).get('landing_page', ''),
                'remote': 'remote' in job.get('location', '').lower(),
                'salary': '',
                'location': job.get('locations', [{}])[0].get('name', '') if job.get('locations') else '',
                'tags': [cat.get('name', '') for cat in job.get('categories', [])],
                'published_date': job.get('publication_date', '')
            })
    
    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_job(self, job):
        score = 0
        score += self.calculate_title_match(job['title'])  * (self.weights['title']       / 100)
        score += self.calculate_skills_match(job['description']) * (self.weights['skills'] / 100)
        score += (100 if job['remote'] else 0)             * (self.weights['remote']       / 100)
        score += self.calculate_salary_match(job['salary'])* (self.weights['salary']       / 100)
        score += 50                                        * (self.weights['company_size'] / 100)
        score += 50                                        * (self.weights['industry']     / 100)
        return round(score, 1)
    
    def calculate_title_match(self, job_title):
        job_title_lower = job_title.lower()
        for target in self.target_titles:
            if target in job_title_lower or job_title_lower in target:
                return 100
        for target in self.target_titles:
            common = set(target.split()) & set(job_title_lower.split())
            if len(common) >= 2:
                return 80
        keywords = ['developer', 'engineer', 'software', 'full stack', 'full-stack']
        if sum(1 for kw in keywords if kw in job_title_lower) >= 2:
            return 60
        return 30
    
    def calculate_skills_match(self, description):
        if not description:
            return 0
        desc_lower = description.lower()
        matches = sum(1 for skill in self.target_skills if skill in desc_lower)
        return min((matches / len(self.target_skills)) * 100, 100) if self.target_skills else 50
    
    def calculate_salary_match(self, salary_info):
        if not salary_info:
            return 50
        numbers = re.findall(r'\$?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)', str(salary_info))
        if numbers:
            max_salary = max(float(n.replace(',', '')) for n in numbers)
            if max_salary >= self.min_salary:        return 100
            if max_salary >= self.min_salary * 0.8:  return 80
            if max_salary >= self.min_salary * 0.6:  return 60
            return 30
        return 50
    
    # ------------------------------------------------------------------
    # Company research — Wikipedia (fixed User-Agent + Referer)
    # ------------------------------------------------------------------

    def research_company(self, company_name):
        if not company_name:
            return "No company name provided."
        try:
            search_url = (
                f"https://en.wikipedia.org/w/api.php"
                f"?action=opensearch&search={quote(company_name)}&limit=3&format=json"
            )
            # Wikipedia blocks default Python urllib; supply a descriptive UA
            wiki_headers = {
                'User-Agent': 'JobScout/1.0 (autonomous job hunting tool; contact: user@example.com)',
                'Accept': 'application/json',
            }
            data = fetch_json(search_url, extra_headers=wiki_headers)
            if not data or len(data) < 2 or not data[1]:
                return f"No Wikipedia page found for {company_name}."
            
            page_title = data[1][0]
            summary_url = (
                f"https://en.wikipedia.org/w/api.php"
                f"?action=query&prop=extracts&exintro&explaintext"
                f"&titles={quote(page_title)}&format=json"
            )
            summary_data = fetch_json(summary_url, extra_headers=wiki_headers)
            if not summary_data:
                return f"Could not fetch Wikipedia summary for {page_title}."
            
            pages = summary_data.get('query', {}).get('pages', {})
            page_id = next(iter(pages.keys()), None)
            if page_id and page_id != '-1':
                extract = pages[page_id].get('extract', 'No summary available.')
                return (
                    f"Company: {company_name}\n"
                    f"Wikipedia Page: {page_title}\n"
                    f"URL: https://en.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}\n\n"
                    f"Summary:\n{extract[:2000]}"
                )
            return f"Wikipedia page '{page_title}' not found."
        except Exception as e:
            return f"Error researching {company_name}: {e}"
    
    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def save_job_folder(self, job, score):
        safe_company = re.sub(r'[^\w\s-]', '', job['company']).strip().replace(' ', '_')
        safe_title   = re.sub(r'[^\w\s-]', '', job['title']).strip().replace(' ', '_')
        folder_name  = f"{safe_company}_{safe_title}"[:50]
        
        job_dir = os.path.join(self.today_dir, folder_name)
        os.makedirs(job_dir, exist_ok=True)
        
        with open(os.path.join(job_dir, 'job_description.txt'), 'w', encoding='utf-8') as f:
            f.write(f"Job Title: {job['title']}\n")
            f.write(f"Company: {job['company']}\n")
            f.write(f"Source: {job['source']}\n")
            f.write(f"Remote: {'Yes' if job['remote'] else 'No'}\n")
            f.write(f"Location: {job.get('location', 'N/A')}\n")
            f.write(f"Salary: {job.get('salary', 'N/A')}\n")
            f.write(f"Published: {job.get('published_date', 'N/A')}\n")
            f.write(f"Apply URL: {job.get('url', 'N/A')}\n\n{'='*50}\n\n")
            f.write(job['description'][:5000])
        
        with open(os.path.join(job_dir, 'match_score.txt'), 'w', encoding='utf-8') as f:
            f.write(f"Match Score: {score}/100\n")
            f.write(f"Scored on: {self.today}\n\nScoring Breakdown:\n")
            f.write(f"- Title Match:  {self.calculate_title_match(job['title'])}/100\n")
            f.write(f"- Skills Match: {self.calculate_skills_match(job['description'])}/100\n")
            f.write(f"- Remote:       {'100/100' if job['remote'] else '0/100'}\n")
            f.write(f"- Salary Match: {self.calculate_salary_match(job.get('salary', ''))}/100\n")
        
        with open(os.path.join(job_dir, 'apply_link.txt'), 'w', encoding='utf-8') as f:
            f.write(job.get('url', 'No apply link available'))
        
        if self.config.getboolean('output', 'research_companies'):
            research = self.research_company(job['company'])
            with open(os.path.join(job_dir, 'company_research.txt'), 'w', encoding='utf-8') as f:
                f.write(f"Company Research: {job['company']}\nResearched on: {self.today}\n\n{'='*50}\n\n")
                f.write(research)
        
        return job_dir
    
    def update_csv_tracker(self, scored_jobs):
        csv_path = os.path.join(RESULTS_DIR, CSV_FILENAME)
        file_exists = os.path.exists(csv_path)
        fieldnames = ['Date Found', 'Job Title', 'Company', 'Score',
                      'Salary', 'Remote', 'Apply Link', 'Status', 'Follow Up Date']
        
        with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for jd in scored_jobs:
                job = jd['job']
                writer.writerow({
                    'Date Found':     self.today,
                    'Job Title':      job['title'],
                    'Company':        job['company'],
                    'Score':          jd['score'],
                    'Salary':         job.get('salary', 'Not specified'),
                    'Remote':         'Yes' if job['remote'] else 'No',
                    'Apply Link':     job.get('url', ''),
                    'Status':         'Not Applied',
                    'Follow Up Date': (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
                })
        print(f"Updated CSV tracker: {csv_path}")
    
    def create_summary(self, top_jobs):
        summary_file = os.path.join(self.today_dir, 'summary.md')
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(f"# Job Scout Summary - {self.today}\n\n")
            f.write(f"**Total jobs fetched:** {len(self.jobs)}\n")
            f.write(f"**Total jobs scored:** {len(self.scored_jobs)}\n")
            f.write(f"**Top {len(top_jobs)} matches:**\n\n")
            for i, jd in enumerate(top_jobs, 1):
                job = jd['job']
                f.write(f"## {i}. {job['title']} - {job['company']} ({jd['score']}/100)\n")
                f.write(f"- **Source:** {job['source']}\n")
                f.write(f"- **Remote:** {'Yes' if job['remote'] else 'No'}\n")
                f.write(f"- **Location:** {job.get('location', 'N/A')}\n")
                f.write(f"- **Salary:** {job.get('salary', 'Not specified')}\n")
                f.write(f"- **Apply:** {job.get('url', 'No link')}\n")
                f.write(f"- **Folder:** {jd.get('folder', 'N/A')}\n\n")
            f.write("\n## Scoring Weights Used\n")
            for k, v in self.weights.items():
                f.write(f"- {k}: {v}%\n")
            f.write("\n## Profile Settings\n")
            f.write(f"- Target Titles: {', '.join(self.target_titles)}\n")
            f.write(f"- Target Skills: {', '.join(self.target_skills[:5])}...\n")
            f.write(f"- Minimum Salary: ${self.min_salary:,}\n")
            f.write(f"- Remote Required: {self.require_remote}\n")
        print(f"Created summary: {summary_file}")
        return summary_file
    
    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def run(self):
        print("=" * 60)
        print("Job Scout - Autonomous Job Hunting Tool")
        print("=" * 60)
        
        print("\n[Step 1] Fetching jobs from APIs...")
        self.fetch_remotive_jobs()
        self.fetch_arbeitnow_jobs()
        self.fetch_remoteok_jobs()
        self.fetch_themuse_jobs()
        print(f"\nTotal jobs fetched: {len(self.jobs)}")
        
        if not self.jobs:
            print("No jobs fetched. Exiting.")
            return
        
        print("\n[Step 2] Scoring jobs...")
        for job in self.jobs:
            self.scored_jobs.append({'job': job, 'score': self.score_job(job)})
        self.scored_jobs.sort(key=lambda x: x['score'], reverse=True)
        
        top_count = min(5, len(self.scored_jobs))
        top_jobs  = self.scored_jobs[:top_count]
        
        print(f"\nTop {top_count} matches:")
        for i, jd in enumerate(top_jobs, 1):
            print(f"  {i}. {jd['job']['title']} at {jd['job']['company']} - {jd['score']}/100")
        
        print("\n[Step 3] Saving top job details...")
        for jd in top_jobs:
            jd['folder'] = os.path.basename(self.save_job_folder(jd['job'], jd['score']))
            print(f"  Saved: {jd['job']['title']} -> {jd['folder']}")
        
        print("\n[Step 4] Updating CSV tracker...")
        self.update_csv_tracker(self.scored_jobs)
        
        print("\n[Step 5] Creating summary...")
        self.create_summary(top_jobs)
        
        print("\n" + "=" * 60)
        print("Job Scout completed successfully!")
        print("=" * 60)
        print(f"\nResults saved to: {self.today_dir}")
        print(f"CSV tracker: {os.path.join(RESULTS_DIR, CSV_FILENAME)}")
        print(f"\nTop job folders:")
        for jd in top_jobs:
            print(f"  - {jd['folder']}")


if __name__ == "__main__":
    scout = JobScout()
    scout.run()