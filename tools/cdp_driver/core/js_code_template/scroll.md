获取元素视口中心坐标，供 scroll 方法定位用
```js
function () {
    var r = this.getBoundingClientRect();
    return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
}
```
