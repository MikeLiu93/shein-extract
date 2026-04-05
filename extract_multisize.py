import requests, json, threading, websocket, time

def cdp_once(ws_url, method, params=None, timeout=30):
    result = {}
    done = threading.Event()
    def on_open(ws):
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
    def on_message(ws, msg):
        d = json.loads(msg)
        if d.get("id") == 1:
            result["data"] = d.get("result", {})
            done.set()
            ws.close()
    def on_error(ws, err):
        result["error"] = str(err)
        done.set()
    ws_app = websocket.WebSocketApp(ws_url, on_open=on_open, on_message=on_message, on_error=on_error)
    threading.Thread(target=ws_app.run_forever, daemon=True).start()
    done.wait(timeout=timeout)
    return result.get("data", {})

resp = requests.get("http://localhost:9222/json")
tabs = resp.json()
ws_url = None
for t in tabs:
    if "shein.com" in t.get("url", ""):
        ws_url = t["webSocketDebuggerUrl"]
        break

# Navigate to a dress with multiple sizes (S, M, L, XL etc.)
MULTI_URL = "https://us.shein.com/SHEIN-EZwear-Women-s-Solid-Color-Loose-Fit-Round-Neck-Drop-Shoulder-Short-Sleeve-T-Shirt-p-26553870.html"
print(f"Navigating to multi-size product: {MULTI_URL}")
nav = cdp_once(ws_url, "Page.navigate", {"url": MULTI_URL})
time.sleep(8)

# Extract sku_list with prices per size
print("\n=== Multi-size SKU list ===\n")
JS1 = r"""
(function() {
    try {
        var multi = window.gbRawData.modules.saleAttr.multiLevelSaleAttribute;
        var skuList = multi.sku_list;
        if (!skuList) return JSON.stringify({error: "no sku_list", keys: Object.keys(multi)});

        var summary = skuList.map(function(s) {
            var sizeAttr = (s.sku_sale_attr || []).find(function(a) { return a.attr_id === "87"; });
            return {
                sku_code: s.sku_code,
                stock: s.stock,
                sizeName: sizeAttr ? sizeAttr.attr_value_name : null,
                sizeAttrValueId: sizeAttr ? sizeAttr.attr_value_id : null,
                sku_sale_attr: s.sku_sale_attr,
                salePrice: s.priceInfo ? s.priceInfo.salePrice : null,
                retailPrice: s.priceInfo ? s.priceInfo.retailPrice : null,
                unitDiscount: s.priceInfo ? s.priceInfo.unitDiscount : null,
                price_salePrice: s.price ? s.price.salePrice : null,
                price_unit_discount: s.price ? s.price.unit_discount : null
            };
        });

        return JSON.stringify({
            goods_id: multi.goods_id,
            skc_name: multi.skc_name,
            skuCount: skuList.length,
            comboStock: multi.comboStock,
            skus: summary
        }, null, 2);
    } catch(e) {
        return JSON.stringify({error: e.message, stack: e.stack});
    }
})()
"""
r1 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS1, "returnByValue": True})
val1 = r1.get("result", {}).get("value", "{}")
try:
    p1 = json.loads(val1)
    print(json.dumps(p1, indent=2)[:10000])
except:
    print(val1[:10000])

# Also get the mainSaleAttribute for this product
print("\n=== Main sale attribute (colors) for this product ===\n")
JS2 = r"""
(function() {
    var main = window.gbRawData.modules.saleAttr.mainSaleAttribute;
    if (!main) return JSON.stringify({error: "none"});
    var info = (main.info || []).map(function(c) {
        return {
            attr_value: c.attr_value,
            attr_value_id: c.attr_value_id,
            goods_id: c.goods_id
        };
    });
    return JSON.stringify({colorCount: info.length, colors: info}, null, 2);
})()
"""
r2 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS2, "returnByValue": True})
val2 = r2.get("result", {}).get("value", "{}")
print(val2[:3000])
