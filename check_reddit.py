import json

with open(r'e:\SCRAPPER\data\mentions_enriched.json', encoding='utf-8') as f:
    d = json.load(f)

out = []
reddit = [r for r in d['records'] if r.get('platform') == 'reddit']
out.append("Reddit in enriched: %d" % len(reddit))
for r in reddit:
    title = (r.get('title') or r.get('text') or '')[:55]
    out.append("  relevance=%s topic=%s | %s" % (
        r.get('relevance', '?'),
        r.get('topic', '?'),
        title
    ))
out.append("")
out.append("meta llm_backend: %s" % d['meta'].get('llm_backend'))
out.append("meta llm_enriched: %s" % d['meta'].get('llm_enriched'))

with open(r'e:\SCRAPPER\check_out.txt', 'w') as f:
    f.write('\n'.join(out))
print("Done - see check_out.txt")
