填充 input 的值
占位字符串: ___value___

```js
function () {
    this.focus();
    this.value = "";
    if (this.tagName == "SELECT") {
        for (let o of this.options) {
            if (o.text.includes(___value___)) {
                o.selected = true;
                break;
            }
        }
        this.dispatchEvent(new Event("change", {bubbles: true}));
    } else {
        this.value = ___value___;
        this.dispatchEvent(new Event("input", {bubbles: true}));
        this.dispatchEvent(new Event("change", {bubbles: true}));
    }
}
```
