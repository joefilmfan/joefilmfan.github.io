# Joseph Kahn site search

A standalone, client-side search page for [josephkahn.com](https://www.josephkahn.com).

The site CMS has no site-wide search or code injection, so this page is meant to live on GitHub Pages and be linked from a SEARCH item in the top menu (a "link" page in the CMS), the same way SHOP points at eBay.

Intended public URL:

https://joefilmfan.github.io/search/

Host it as the `/search/` folder in the existing `joefilmfan/joefilmfan.github.io` user-site repo. Do not change any other files in that repo (it already holds a Tesla `.well-known` file).

## Files

- `index.html` — search UI (no analytics, no external scripts or fonts)
- `projects.json` — crawled index of public projects
- `rebuild.py` — re-crawls the public site and regenerates `projects.json`

## Refresh the index

When new projects are added to josephkahn.com:

```bash
python3 rebuild.py
```

Then commit and push the updated `projects.json`. The script reads the header FILTER links, crawls Featured, Commercials, Music Videos, Films, Short Films, and TV, and checks Press, Bio, and Contact (those pages have no project grids).

A few Featured tiles on the live site have blank CMS captions. The rebuild script infers a label from the thumbnail filename for those, and sets `title_inferred: true`.
