将页面 DOM 转为 Markdown 文本。优先从 &lt;article&gt; 或 &lt;main&gt; 提取，否则遍历 &lt;body&gt;。
忽略 script、style、noscript、iframe、svg、nav、footer、aside、header 及隐藏元素。

核心转换：
- h1-h6 → # ~ ######
- p → 段落
- a → [text](url)
- strong/b → **text**，em/i → *text*，del/s → ~~text~~
- ul/ol/li → 列表
- pre → 代码块
- blockquote → 引用
- table → 表格
- img → ![alt](src)
- hr → ---

```js
(function () {
    /* 需要跳过的标签 */
    var SKIP = { script:1, style:1, noscript:1, iframe:1, svg:1, template:1, link:1, meta:1, nav:1, footer:1, aside:1, header:1 };

    function hidden(el) {
        if (el.hidden) return 1;
        var s = window.getComputedStyle(el);
        if (s.display === 'none' || s.visibility === 'hidden') return 1;
        if (el.getAttribute('aria-hidden') === 'true') return 1;
        return 0;
    }

    function skip(el) {
        if (!el || !el.tagName) return 1;
        if (SKIP[el.tagName.toLowerCase()]) return 1;
        if (hidden(el)) return 1;
        return 0;
    }

    /* 遍历内联元素，生成带格式的内联 markdown */
    function imd(el) {
        var o = '';
        var cs = el.childNodes;
        for (var i = 0; i < cs.length; i++) {
            var n = cs[i];
            if (n.nodeType === 3) {
                o += n.textContent;
            } else if (n.nodeType === 1) {
                if (skip(n)) continue;
                var t = n.tagName.toLowerCase();
                if (t === 'br') {
                    o += '\n';
                } else if (t === 'a') {
                    var h = n.getAttribute('href') || '';
                    var l = imd(n).trim();
                    if (l && h && h.indexOf('javascript:') !== 0) {
                        o += '[' + l + '](' + h + ')';
                    } else {
                        o += l;
                    }
                } else if (t === 'strong' || t === 'b') {
                    o += '**' + imd(n) + '**';
                } else if (t === 'em' || t === 'i') {
                    o += '*' + imd(n) + '*';
                } else if (t === 'code' || t === 'kbd' || t === 'samp') {
                    o += '`' + n.textContent + '`';
                } else if (t === 'img') {
                    var alt = n.getAttribute('alt') || '';
                    var src = n.getAttribute('src') || '';
                    if (src && alt) o += '![' + alt + '](' + src + ')';
                } else if (t === 'del' || t === 's' || t === 'strike') {
                    o += '~~' + imd(n) + '~~';
                } else {
                    o += imd(n);
                }
            }
        }
        return o;
    }

    var md = [];
    var pb = 1; /* previous line was blank */

    function eb() {
        if (!pb) { md.push(''); pb = 1; }
    }

    function al(s) {
        md.push(s); pb = 0;
    }

    function ab(s) {
        eb(); al(s); md.push(''); pb = 1;
    }

    /* 递归处理块级元素 */
    function proc(el) {
        if (!el || !el.tagName || skip(el)) return;
        var t = el.tagName.toLowerCase();

        /* 标题 */
        if (t === 'h1' || t === 'h2' || t === 'h3' || t === 'h4' || t === 'h5' || t === 'h6') {
            var lv = parseInt(t[1]);
            var tx = imd(el).replace(/\n/g, ' ').trim();
            if (tx) {
                var pf = '';
                for (var j = 0; j < lv; j++) pf += '#';
                ab(pf + ' ' + tx);
            }
            return;
        }

        /* 段落 */
        if (t === 'p') {
            var tx = imd(el).trim();
            if (tx) ab(tx);
            return;
        }

        /* 代码块 */
        if (t === 'pre') {
            var cd = el.querySelector('code');
            var tx = (cd || el).textContent;
            if (tx.trim()) {
                eb(); al('```'); al(tx.trim()); al('```');
                md.push(''); pb = 1;
            }
            return;
        }

        /* 引用 */
        if (t === 'blockquote') {
            var tx = imd(el).trim();
            if (tx) {
                eb();
                var ls = tx.split('\n');
                for (var k = 0; k < ls.length; k++) al('> ' + ls[k]);
                md.push(''); pb = 1;
            }
            return;
        }

        /* 无序列表 */
        if (t === 'ul') {
            eb();
            var its = el.children;
            for (var m = 0; m < its.length; m++) {
                var li = its[m];
                if (li.tagName && li.tagName.toLowerCase() === 'li') {
                    var tx = imd(li).trim();
                    if (tx) al('- ' + tx);
                }
            }
            md.push(''); pb = 1;
            return;
        }

        /* 有序列表 */
        if (t === 'ol') {
            eb();
            var its = el.children;
            var idx = 1;
            for (var n = 0; n < its.length; n++) {
                var li = its[n];
                if (li.tagName && li.tagName.toLowerCase() === 'li') {
                    var tx = imd(li).trim();
                    if (tx) { al(idx + '. ' + tx); idx++; }
                }
            }
            md.push(''); pb = 1;
            return;
        }

        /* 表格 */
        if (t === 'table') {
            eb();
            var rows = el.querySelectorAll('tr');
            var hdr = 1;
            for (var r = 0; r < rows.length; r++) {
                var cls = rows[r].querySelectorAll('th, td');
                var pts = [];
                for (var c = 0; c < cls.length; c++) {
                    pts.push(imd(cls[c]).trim().replace(/\|/g, '\\|').replace(/\n/g, ' '));
                }
                if (pts.length) {
                    al('| ' + pts.join(' | ') + ' |');
                    if (hdr && rows[r].querySelector('th')) {
                        var sep = [];
                        for (var s = 0; s < pts.length; s++) sep.push('---');
                        al('| ' + sep.join(' | ') + ' |');
                        hdr = 0;
                    }
                }
            }
            md.push(''); pb = 1;
            return;
        }

        /* 分割线 */
        if (t === 'hr') {
            ab('---');
            return;
        }

        /* figure：仅处理子元素 */
        if (t === 'figure') {
            for (var f = 0; f < el.children.length; f++) proc(el.children[f]);
            return;
        }
        if (t === 'figcaption') {
            var tx = imd(el).trim();
            if (tx) al(tx);
            return;
        }

        /* details / summary */
        if (t === 'details') {
            for (var d = 0; d < el.children.length; d++) proc(el.children[d]);
            return;
        }
        if (t === 'summary') {
            var tx = imd(el).trim();
            if (tx) ab('**' + tx + '**');
            return;
        }

        /* 容器元素：递归处理子节点 */
        if (t === 'div' || t === 'section' || t === 'article' || t === 'main' || t === 'fieldset' || t === 'form') {
            for (var g = 0; g < el.children.length; g++) proc(el.children[g]);
            return;
        }

        /* 兜底：按文本长度决定是块还是行内 */
        var tx = imd(el).trim();
        if (tx && tx.length > 60) {
            ab(tx);
        } else if (tx) {
            al(tx);
        }
    }

    /* 定位内容根节点 */
    var root = document.querySelector('article') || document.querySelector('main') ||
               document.querySelector('[role="main"]') || document.body;

    /* 克隆后清理非内容元素，避免修改原始 DOM */
    root = root.cloneNode(true);
    var rm = root.querySelectorAll('script, style, noscript, iframe, svg, nav, footer, aside, header, template');
    for (var x = 0; x < rm.length; x++) rm[x].remove();

    for (var y = 0; y < root.children.length; y++) proc(root.children[y]);

    return md.join('\n').replace(/\n{3,}/g, '\n\n').trim();
})()
```
