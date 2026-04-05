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

# Navigate back to original product
ORIG_URL = "https://us.shein.com/Armless-Sofa-Bed-Cover-Folding-Sofa-Cover-Futon-Velvet-Stretch-Couch-Slipcover-Velvet-Armless-Sofa-Bed-Cover-Stretch-Folding-Slipcover-For-Living-Roon-p-41479813.html?main_attr=27_2486"
print(f"Navigating back to original product...")
cdp_once(ws_url, "Page.navigate", {"url": ORIG_URL})
time.sleep(8)

# Get sku_sale_attr for the original product
print("=== Original product: sku_sale_attr ===\n")
JS1 = r"""
(function() {
    var multi = window.gbRawData.modules.saleAttr.multiLevelSaleAttribute;
    var skuList = multi.sku_list;
    return JSON.stringify({
        goods_id: multi.goods_id,
        skuCount: skuList.length,
        firstSkuSaleAttr: skuList[0].sku_sale_attr,
        firstSkuCode: skuList[0].sku_code
    }, null, 2);
})()
"""
r1 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS1, "returnByValue": True})
print(r1.get("result", {}).get("value", "{}"))

# Get the init_sku_info from pageInfo (may contain initial SKU selection info)
print("\n=== pageInfo.init_sku_info ===\n")
JS2 = r"""
(function() {
    var pageInfo = window.gbRawData.modules.pageInfo;
    return JSON.stringify({
        init_sku_info: pageInfo.init_sku_info,
        templateType: pageInfo.templateType
    }, null, 2);
})()
"""
r2 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS2, "returnByValue": True})
print(r2.get("result", {}).get("value", "{}"))

# Check mallInfo
print("\n=== mallInfo ===\n")
JS3 = r"""
(function() {
    return JSON.stringify(window.gbRawData.modules.mallInfo, null, 2);
})()
"""
r3 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS3, "returnByValue": True})
print(r3.get("result", {}).get("value", "{}"))

# Verify the script location
print("\n=== Script location verification ===\n")
JS4 = r"""
(function() {
    var scripts = document.querySelectorAll('script:not([src])');
    for (var i = 0; i < scripts.length; i++) {
        var text = scripts[i].textContent || '';
        if (text.indexOf('gbRawData') !== -1 && text.indexOf('sku_list') !== -1) {
            return JSON.stringify({
                scriptIndex: i,
                scriptLength: text.length,
                startsWithSnippet: text.substring(0, 100),
                containsGbRawData: true,
                gbRawDataPosition: text.indexOf('gbRawData'),
                nearbyContext: text.substring(text.indexOf('gbRawData') - 10, text.indexOf('gbRawData') + 50)
            });
        }
    }
    return JSON.stringify({error: "not found"});
})()
"""
r4 = cdp_once(ws_url, "Runtime.evaluate", {"expression": JS4, "returnByValue": True})
val4 = r4.get("result", {}).get("value", "{}")
try:
    p4 = json.loads(val4)
    print(json.dumps(p4, indent=2))
except:
    print(val4)
