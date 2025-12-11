import requests
import json
import os

TOKEN_FILE = "GitHubToken.txt"
REPO_OWNER = "cmc0619"
REPO_NAME = "Traloxolcus-Claude"

def load_token():
    # Look in the parent directory of the scripts folder
    token_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), TOKEN_FILE)
    with open(token_path, "r") as f:
        return f.read().strip()

def fetch_all_pages(url, headers):
    results = []
    page = 1
    while True:
        response = requests.get(f"{url}?page={page}&per_page=100", headers=headers)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"Error fetching {url}: {e}")
            break
            
        data = response.json()
        if not data:
            break
        results.extend(data)
        page += 1
    return results

def main():
    try:
        token = load_token()
    except FileNotFoundError:
        print(f"Error: {TOKEN_FILE} not found in parent directory.")
        return

    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    
    print(f"Fetching PRs for {REPO_OWNER}/{REPO_NAME}...")
    prs_url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls"
    
    all_prs = []
    page = 1
    while True:
        r = requests.get(f"{prs_url}?state=all&page={page}&per_page=100", headers=headers)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        all_prs.extend(data)
        page += 1
        
    print(f"Found {len(all_prs)} PRs.")
    
    all_comments = []
    
    for pr in all_prs:
        pr_number = pr['number']
        # print(f"Fetching comments for PR #{pr_number} ({pr['title']})...")
        
        # Review comments (on code files)
        review_comments = fetch_all_pages(f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/pulls/{pr_number}/comments", headers)
        for c in review_comments:
            c['pr_number'] = pr_number
            c['pr_title'] = pr['title']
            c['comment_type'] = 'review_comment'
        
        # Issue comments (general conversation)
        issue_comments = fetch_all_pages(f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/issues/{pr_number}/comments", headers)
        for c in issue_comments:
            c['pr_number'] = pr_number
            c['pr_title'] = pr['title']
            c['comment_type'] = 'issue_comment'
            
        all_comments.extend(review_comments)
        all_comments.extend(issue_comments)
        
    # Save to file
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pr_data.json")
    with open(output_path, "w") as f:
        json.dump(all_comments, f, indent=2)
        
    print(f"Saved {len(all_comments)} comments to {output_path}.")
    
    # Analyzer Users
    users = set()
    bots = set()
    for c in all_comments:
        user = c['user']
        users.add(user['login'])
        if user['type'] == 'Bot' or 'bot' in user['login'].lower():
            bots.add(user['login'])
            
    print("\n--- Users Found ---")
    for u in users:
        print(u)
        
    print("\n--- Potential Bots/AI ---")
    for b in bots:
        print(b)

if __name__ == "__main__":
    main()
