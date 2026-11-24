---
title: "代理 IP 到手先测一测：能连上，不等于能放心用"
description: "刚到手一批代理 IP，别急着往模拟器里填。先花几分钟测一测——能连上和能放心用，是两回事。连不上，任务跑不起来 […]"
date: 2026-11-18
tags: [IP检测, Python, SOCKS5, 代理IP, 新手教程]
canonical: https://www.59pk.net/225.html
---

刚到手一批代理 IP，别急着往模拟器里填。先花几分钟测一测——能连上和能放心用，是两回事。连不上，任务跑不起来；连上了但漏了真实 IP，更糟：等于没藏，还可能把号搭进去。所以测的时候就看两样：通不通，漏不漏。

## 先看通不通，再看快不快

测代理，第一步是让它真的去访问一次目标网站，模拟真实使用场景。量少的时候不用写脚本，一条 curl 就够了：

```
curl -x http://代理IP:端口 http://httpbin.org/ip --max-time 5
```

返回 200，响应里能看到代理的出口 IP，就算初步可用。ping 也能探，但 ping 只能告诉你主机通不通，验证不了代理协议和 HTTP 请求正不正常，单独拿它当结论不够。

通了还得看快不快。常用的参考值就三条：丢包率控制在 5% 以内，平均延迟低于 200ms，超时设 3 到 5 秒。超时了就按不可用处理，别抱侥幸心理。具体的数字按业务来，游戏和采集的要求本来就不一样。连上之后请求超时、断断续续，[按 HTTP 代理请求超时的思路查一遍](https://www.59pk.net/91.html)，多半是节点、线路或者本地网络其中一环的问题。

## 再看它漏没漏你的真实 IP

光连上还不够。代理的本分是把真实 IP 藏住，请求头里一旦带了 X-Forwarded-For 这类真实 IP 信息，这条线路基本等于白用。

验的方法也简单：先记下不走代理时的真实出口 IP，[站里这个 IP 检测页](https://www.59pk.net/ipcheck)就能查；再走代理访问一次目标站，对比它看到的 IP。两个不一样、且响应里不含真实 IP，才算匿名有效。[Socks5 线路从哪里来、怎么判断一条线路干不干净](https://www.59pk.net/79.html)，纯净度也是同一回事，公共代理池里的“脏 IP”本来就是封号的主要原因之一，测的时候顺手一起筛掉。

## 量大就别手动测了，写个脚本一次跑完

![图片[1]-天天向上](https://oss.file.59pk.net/wp-content/uploads/2026/11/20261118091848343.webp/59pk)

手里几条代理，curl 一条条探没问题；几百上千条还手动测，测到天黑也测不完。写个 Python 脚本，让它并发跑，跑完按延迟排个序：

```
import requests
import concurrent.futures
from datetime import datetime

def test_single_proxy(proxy, real_ip=None):
    try:
        proxies = {
            'http': f'http://{proxy}',
            'https': f'http://{proxy}'
        }
        start = datetime.now()
        response = requests.get(
            'http://httpbin.org/ip',
            proxies=proxies,
            timeout=5
        )
        latency = (datetime.now() - start).total_seconds() * 1000

        if response.status_code == 200:
            data = response.json()
            origin = str(data.get('origin', ''))
            if real_ip and real_ip not in origin:
                anonymity = '高匿'
            elif real_ip:
                anonymity = '透明（泄露真实 IP）'
            else:
                anonymity = '待确认'
            return {
                'proxy': proxy,
                'status': '可用',
                'status_code': response.status_code,
                'latency': round(latency, 2),
                'anonymity': anonymity
            }
    except Exception as e:
        return {
            'proxy': proxy,
            'status': f'不可用: {str(e)[:50]}',
            'status_code': None,
            'latency': None,
            'anonymity': '未知'
        }
    return {'proxy': proxy, 'status': '未知', 'status_code': None, 'latency': None, 'anonymity': '未知'}

def batch_test(proxy_list, max_workers=20):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_proxy = {
            executor.submit(test_single_proxy, p): p
            for p in proxy_list
        }
        for future in concurrent.futures.as_completed(future_to_proxy):
            results.append(future.result())
    return sorted(results, key=lambda x: (x['latency'] is None, x['latency']))

# 使用示例
proxy_list = [
    '123.123.123.123:8080',
    '111.111.111.111:3128',
]

results = batch_test(proxy_list)
for i, result in enumerate(results, 1):
    status_symbol = '✓' if result['status'] == '可用' else '✗'
    print(f"[{i:03d}/{len(proxy_list):03d}] {status_symbol} {result['proxy']:30} {result.get('status', '')}")
```

脚本不复杂：每条代理发一次请求去 httpbin.org/ip，超时 5 秒，返回 200 就是可用，顺手记下延迟；再拿响应里的 origin 和不走代理时的真实 IP 比一比，含真实 IP 就是透明，不含就是高匿。20 个线程并发跑，几百条代理几分钟就出结果。

注意两点。第一，原文的代码里 datetime 用了却没导入，直接复制运行会报错，这里补上了 `from datetime import datetime`；匿名判断也改成了拿真实出口 IP 对比，比原文粗糙的字符串比对准一些。第二，示例里的 123.123.123.123:8080 这类地址是占位写法，跑之前换成你自己的代理列表。

[多开模拟器之前，先把这批线路测一遍](https://www.59pk.net/135.html)，窗口一多，坏线路混进去，查起来更费劲。

测完把三类剔掉：连不上的、超时的、漏真实 IP 的。剩下的按延迟排个序，好线路先用。还有一点：代理的可用状态会随时间变，这次能用不代表下个月还能用，定期复测一次，[申请代理 IP 的时候挑类型也是同一个道理](https://www.59pk.net/221.html)，类型选对了，线路也得勤验。

说到底，测代理 IP 没什么花活：发一次真实请求，看状态码、看延迟、看它漏没漏真实 IP。量少 curl 探一下，量大脚本跑一遍，测完剔掉不能用的，剩下的定期复测。代理是拿来藏身份、稳业务的，测这一步省不得。

