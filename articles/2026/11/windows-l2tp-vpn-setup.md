---
title: "Windows 电脑 L2TP VPN 设置"
description: "L2TP 是第二层隧道协议（Layer 2 Tunneling Protocol），它自己不加密，真正加密的是 […]"
date: 2026-11-19
tags: [IPsec, L2TP, VPN, Windows, 新手教程]
canonical: https://www.59pk.net/290.html
---

L2TP 是第二层隧道协议（Layer 2 Tunneling Protocol），它自己不加密，真正加密的是外面那层 IPsec，所以完整的名字叫 L2TP/IPsec。Windows 10 和 11 自带客户端，不用装任何软件，在设置里填几个参数就能连。

![你的电脑 → L2TP 隧道（IPsec 加密）→ VPN 服务器 → 目标网站](https://oss.file.59pk.net/wp-content/uploads/2026/11/20261119101352745.webp/59pk)

## 先备齐三样东西，缺一样都连不上

动手之前，先从 VPN 服务商或单位管理员那里拿到三样东西：服务器地址（IP 或域名）、预共享密钥、用户名和密码。

预共享密钥是 IPsec 认证用的共享密码，服务器和客户端两边必须一模一样，错一个字符都连不上。拿的时候别手打，复制粘贴最稳。

## Windows 11 六步加好连接，系统自带就能连

![六步加好 L2TP 连接](https://oss.file.59pk.net/wp-content/uploads/2026/11/20261119101359929.webp/59pk)
![设置 → 网络和 Internet → VPN 页面，点右上角“添加 VPN”](https://oss.file.59pk.net/wp-content/uploads/2026/11/20261119102618804.webp/59pk)

按 Win+I 打开”设置”，点”网络和 Internet”，再点”VPN”，就到了这个页面，右上角点”添加 VPN”。

![“添加 VPN 连接”表单：VPN 提供商、连接名称、服务器地址、VPN 类型、登录信息](https://oss.file.59pk.net/wp-content/uploads/2026/11/20261119103207367.webp/59pk)

“VPN 提供商”选”Windows (内置）”，”连接名称”随便起一个，比如”公司 VPN”；”服务器名称或地址”填服务商或管理员给的地址；”VPN 类型”选”使用预共享密钥的 L2TP/IPsec”，在”预共享密钥”里填密钥；”登录信息类型”选”用户名和密码”，填用户名和密码，勾上”记住我的登录信息”，点”保存”。截图里的服务器地址和用户名是示例，按你自己的填。。

![保存好的连接出现在列表里，点“连接”就能连上](https://oss.file.59pk.net/wp-content/uploads/2026/11/20261119102632892.webp/59pk)

回到 VPN 页面，刚建好的连接出现在列表里，点”连接”，就连上了。

## Windows 10 同一个入口，字段一模一样

Windows 10 的路子一样：设置 → 网络和 Internet → VPN，按钮叫”添加 VPN 连接”，其他字段一模一样，照着上面填就行。

## 连上之后先确认，出口 IP 变了才算通

连上之后别急着用，先确认隧道真的通了。打开浏览器，到[IP 检测工具](https://www.59pk.net/ipcheck)上看一眼出口 IP 变没变；要连公司内网的话，ping 一下内网服务器地址，通了就说明隧道通了。

## 连不上先看错误代码，代码告诉你查哪里

| 错误代码 | 一般是什么意思 | 先查什么 |
| --- | --- | --- |
| 809 | 远程服务器没响应，连接建不起来 | 路由器或防火墙挡了 UDP 500、1701、4500；服务器或客户端在 NAT 后面（比如家用路由器） |
| 789 | 安全层协商失败 | 预共享密钥两边不一致，重新核对；或者 IPsec 被禁用了 |
| 691 | 用户名或密码被拒绝 | 核对账号密码，注意大小写和多余空格 |
| 720 | 到远程计算机的连接建不起来 | WAN Miniport 适配器出问题：设备管理器 → 网络适配器 → 卸载所有”WAN Miniport”开头的适配器 → 操作 → 扫描检测硬件改动，让系统重装 |

809 最常见，修法是改一次注册表，这是微软 KB926179 给的办法。以管理员身份打开命令提示符，运行下面这行命令，然后重启电脑。改之前先把注册表备份一下，注册表编辑器里点”文件”→”导出”就行：

```
REG ADD HKLM\SYSTEM\CurrentControlSet\Services\PolicyAgent /v AssumeUDPEncapsulationContextOnSendRule /t REG_DWORD /d 0x2 /f
```

值 2 的意思是服务器和客户端都在 NAT 后面时也允许；如果只有服务器在 NAT 后面，值 1 就够了。也可以在注册表编辑器里手动加：按 Win+R 输入 regedit，找到 HKEY\_LOCAL\_MACHINE\SYSTEM\CurrentControlSet\Services\PolicyAgent，新建一个 DWORD (32 位） 值，名字叫 AssumeUDPEncapsulationContextOnSendRule，值填 2，重启电脑。

如果 IPsec 被禁用了，也会连不上，再运行下面这行命令重新启用，同样要重启：

```
REG ADD HKLM\SYSTEM\CurrentControlSet\Services\RasMan\Parameters /v ProhibitIpSec /t REG_DWORD /d 0x0 /f
```

## L2TP 够不够安全，全看 IPsec 有没有开

L2TP 本身不加密，加密全靠 IPsec，所以一定要选”使用预共享密钥的 L2TP/IPsec”，别选裸 L2TP。预共享密钥就是个密码，别用 123456 这种，越长越乱越好，泄露了就等于门没锁。

PPTP 别用，早就被攻破了。L2TP 是老协议，只支持 IKEv1，够用，但不是最强的选择；如果服务商还提供 IKEv2、OpenVPN、WireGuard，新的优先。

设好一次，以后点一下就能连。如果只想让某个程序走代理，不用搭 VPN，[SSTap](https://www.59pk.net/183.html) 这样的客户端也行。

