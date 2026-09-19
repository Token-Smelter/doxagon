import urllib.request
import urllib.parse
import re
import sys

def search(query):
    print(f"Searching for: {query}")
    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(
        url, 
        data=b"", 
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    )
    try:
        html = urllib.request.urlopen(req).read().decode('utf-8')
        results = []
        blocks = html.split('<div class="result ')
        for block in blocks[1:]:
            try:
                title_start = block.index('<h2 class="result__title">')
                title_end = block.index('</h2>', title_start)
                title_html = block[title_start:title_end]
                
                link_start = title_html.index('href="') + 6
                link_end = title_html.index('"', link_start)
                link = title_html[link_start:link_end]
                
                if 'uddg=' in link:
                    link = urllib.parse.unquote(link.split('uddg=')[1].split('&')[0])
                    
                text_start = title_html.index('>', title_html.index('<a')) + 1
                text_end = title_html.index('</a>')
                title = re.sub(r'<[^>]+>', '', title_html[text_start:text_end]).strip()
                
                snippet_start = block.index('<a class="result__snippet')
                snippet_text_start = block.index('>', snippet_start) + 1
                snippet_end = block.index('</a>', snippet_text_start)
                snippet = re.sub(r'<[^>]+>', '', block[snippet_text_start:snippet_end]).strip()
                
                results.append((title, link, snippet))
            except ValueError:
                continue
                
        for i, res in enumerate(results[:10]):
            snip = res[2].replace('\n', ' ').strip()
            sentences = re.split(r'(?<=[.!?]) +', snip)
            if len(sentences) > 2:
                snip = ' '.join(sentences[:2])
            print(f"{i+1}. [{res[0]}]({res[1]})\n   {snip}")
    except Exception as e:
        print(f"Error searching for {query}: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        for q in sys.argv[1:]:
            search(q)
    else:
        print("Usage: python3 search.py 'query1' 'query2' ...")
