import json
import os
from collections import defaultdict

INPUT_FILE = "pr_data.json"
OUTPUT_FILE = "comments_report.md"
AI_USERS = {"coderabbitai[bot]", "chatgpt-codex-connector[bot]"}

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(script_dir, INPUT_FILE)
    output_path = os.path.join(script_dir, OUTPUT_FILE)
    
    with open(input_path, 'r', encoding='utf-8') as f:
        comments = json.load(f)
        
    # Index comments by ID for threading
    comments_by_id = {c['id']: c for c in comments}
    # Index replies by parent ID
    replies_by_parent = defaultdict(list)
    
    for c in comments:
        # Check for in_reply_to_id (standard for PR review comments)
        parent_id = c.get('in_reply_to_id')
        if parent_id:
            replies_by_parent[parent_id].append(c)
            
    # Filter for AI comments
    ai_comments = [c for c in comments if c['user']['login'] in AI_USERS]
    
    unaddressed = []
    addressed = []
    
    for c in ai_comments:
        is_addressed = False
        status_reason = "Unknown"
        
        # Heuristic 1: CodeRabbit "Addressed in commit" marker
        if "Addressed in commit" in c['body']:
            is_addressed = True
            status_reason = "Marked as addressed by bot"
            
        # Determine final bucket
        if is_addressed:
            addressed.append(c)
        else:
            # Check for replies
            replies = replies_by_parent.get(c['id'], [])
            unaddressed.append((c, replies))

    # Generate Report
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# AI Review Analysis Report\n\n")
        f.write(f"**Total AI Comments:** {len(ai_comments)}\n")
        f.write(f"**Addressed/Fixed:** {len(addressed)}\n")
        f.write(f"**Unaddressed/Open:** {len(unaddressed)}\n\n")
        
        if unaddressed:
            f.write("## Unaddressed Issues\n\n")
            
            # Group by PR
            by_pr = defaultdict(list)
            for c, replies in unaddressed:
                by_pr[f"PR #{c['pr_number']}: {c.get('pr_title', 'Unknown')}"].append((c, replies))
                
            for pr_title, items in by_pr.items():
                f.write(f"### {pr_title}\n\n")
                for c, replies in items:
                    path = c.get('path', 'Unknown file')
                    line = c.get('line') or c.get('original_line') or '?'
                    
                    f.write(f"- **{c['user']['login']}** (`{path}:{line}`)\n")
                    
                    # Extract summary from body
                    # Use first non-empty line
                    lines = [l for l in c['body'].split('\n') if l.strip()]
                    summary = lines[0] if lines else "No text"
                    # Remove markdown logic from summary if complex
                    if len(summary) > 150:
                        summary = summary[:150] + "..."
                    
                    f.write(f"  > {summary}\n\n")
                    f.write(f"  - [View Comment]({c['html_url']})\n")
                    
                    if replies:
                        f.write(f"  - *Replies: {len(replies)}*\n")
                        for r in replies:
                            reply_body = r['body'].replace('\n', ' ')
                            if len(reply_body) > 60:
                                reply_body = reply_body[:60] + "..."
                            f.write(f"    - **{r['user']['login']}**: {reply_body}\n")
                    f.write("\n")
                    
    print(f"Report generated: {output_path}")

if __name__ == "__main__":
    main()
