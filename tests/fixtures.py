RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Новости</title>
<item><title>Третья новость</title><link>https://news.example/3?utm_source=rss</link>
  <description>&lt;p&gt;Текст &lt;b&gt;третьей&lt;/b&gt; новости&lt;/p&gt;</description>
  <pubDate>Mon, 07 Jan 2030 12:00:00 GMT</pubDate></item>
<item><title>Вторая новость</title><link>https://news.example/2</link>
  <description>Текст второй</description><pubDate>Mon, 07 Jan 2030 11:00:00 GMT</pubDate></item>
<item><title>Первая новость</title><link>https://news.example/1</link>
  <description>Текст первой</description><pubDate>Mon, 07 Jan 2030 10:00:00 GMT</pubDate></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Блог</title>
<entry><title>Запись Atom</title><link rel="alternate" href="https://blog.example/post-1"/>
  <link rel="edit" href="https://blog.example/edit/1"/>
  <summary>Кратко о записи</summary><updated>2030-01-07T09:30:00Z</updated></entry>
</feed>"""

HTML = """<html><body>
<nav><a href="/about">О нас</a></nav>
<div class="list">
  <a href="/news/2030/01/07/obnovlenie-servisa">Обновление сервиса: что изменилось</a>
  <a href="/news/2030/01/06/novyj-tarif">Новый тариф для малого бизнеса</a>
  <a href="/news/2030/01/06/novyj-tarif">Читать</a>
  <a href="https://other.example/news/x">Чужая ссылка с длинным текстом</a>
</div></body></html>"""

BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>
<rss><channel><item><title>&lol2;</title></item></channel></rss>"""


def rss_with(*titles, base="https://news.example/"):
    """Feed with the given titles, newest first, links derived from titles."""
    items = "".join(
        f"<item><title>{t}</title><link>{base}{abs(hash(t)) % 10**8}</link>"
        f"<pubDate>Mon, 07 Jan 2030 {10 + len(titles) - i:02d}:00:00 GMT</pubDate></item>"
        for i, t in enumerate(titles)
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{items}</channel></rss>'
