# 📚 Voice Robot 开放 REST API 接口文档

本文档说明 Voice Robot 系统对外提供的核心 HTTP REST API 规格，包含设备标识获取与用户信息 (租户、用户、组织、行政区划等) 动态推送接口。

---

## 目录
1. [获取设备唯一 ID (`GET /device_id`)](#1-获取设备唯一-id-get-device_id)
2. [动态推送/更新用户信息 (`POST /api/user_info`)](#2-动态推送更新用户信息-post-apiuser_info)

---

### 1. 获取设备唯一 ID (`GET /device_id`)

#### 描述
基于当前运行主机的 Hostname 与网卡 MAC 地址，生成唯一的 UUID 标识字符串，用于唯一标识当前智能终端设备。

- **HTTP 方法**: `GET`
- **请求 URL**: `http://127.0.0.1:10850/device_id`
- **Content-Type**: `application/json`

#### 请求参数
无

#### `curl` 请求示例
```bash
curl -X GET http://127.0.0.1:10850/device_id
```

#### 成功响应示例 (`200 OK`)
```json
{
  "device_id": "a1b2c3d4e5f67890123456789abcdef0"
}
```

#### 响应字段说明
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `device_id` | `string` | 32位 16 进制字符串格式的设备唯一 ID |

---

### 2. 动态推送/更新用户信息 (`POST /api/user_info`)

#### 描述
实时在线推送/更新当前系统的全量用户信息，包含 **租户 (tenantId / tenantName)**、**用户 (userId / userName)**、**组织 (orgId / orgName)** 及 **行政区划/地区名称 (areaCode / areaName)** 等。

调用该接口后：
1. 传入的 `areaName`（地区名称，如 `"歙县"`）生效优先级将自动提升为最高级的 **`HTTP API Override`**，超越本地配置文件与 IP 自动定位；
2. 系统会自动向所有连接的客户端与可视化大屏实时推送 **`user_info_update`** 全量广播；
3. 系统将自动根据 `areaName` 发起最新的天气查询并推送全网 **`weather_data`** 广播，驱动前端卡片与界面零延迟联动更新。

- **HTTP 方法**: `POST`
- **请求 URL**: `http://127.0.0.1:10850/api/user_info`
- **Content-Type**: `application/json`

#### 请求体参数 (Request Body)
| 参数名 | 类型 | 是否必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `timestamp` | `string` | 否 | 时间戳字符串 | `"2026-07-29 17:50:21"` |
| `tenantId` | `string` | 否 | 租户唯一标识 ID | `"37d179eee0c045aea2884ecc7c45c086"` |
| `userId` | `string` | 否 | 用户唯一标识 ID | `"51460163d42a4db0b290e5f0fee88e4d"` |
| `orgId` | `string` | 否 | 组织/机构 ID | `"61a03345abf140ae9ad6ebb54c6c9479"` |
| `tenantType` | `string` | 否 | 租户类型编码 | `""` |
| `areaCode` | `string` | 否 | 行政区划编码 | `"341021"` |
| `tenantName` | `string` | 否 | 租户系统名称 | `"歙县综合减灾会商研判系统"` |
| `userName` | `string` | 否 | 用户账号/姓名 | `"sxyjj"` |
| `orgName` | `string` | 否 | 组织/终端名称 | `"小安知险县域终端"` |
| `tenantTypeName` | `string` | 否 | 租户类型名称 | `"应急管理"` |
| `areaName` | `string` | 否 | 地区名称 (作为聚焦城市) | `"歙县"` |

#### `curl` 请求示例
```bash
curl -X POST http://127.0.0.1:10850/api/user_info \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2026-07-29 17:50:21",
    "tenantId": "37d179eee0c045aea2884ecc7c45c086",
    "userId": "51460163d42a4db0b290e5f0fee88e4d",
    "orgId": "61a03345abf140ae9ad6ebb54c6c9479",
    "tenantType": "",
    "areaCode": "341021",
    "tenantName": "歙县综合减灾会商研判系统",
    "userName": "sxyjj",
    "orgName": "小安知险县域终端",
    "tenantTypeName": "应急管理",
    "areaName": "歙县"
  }'
```

#### 成功响应示例 (`200 OK`)
```json
{
  "status": "success",
  "user_info": {
    "timestamp": "2026-07-29 17:50:21",
    "tenantId": "37d179eee0c045aea2884ecc7c45c086",
    "userId": "51460163d42a4db0b290e5f0fee88e4d",
    "orgId": "61a03345abf140ae9ad6ebb54c6c9479",
    "tenantType": "",
    "areaCode": "341021",
    "tenantName": "歙县综合减灾会商研判系统",
    "userName": "sxyjj",
    "orgName": "小安知险县域终端",
    "tenantTypeName": "应急管理",
    "areaName": "歙县",
    "effective_city": "歙县",
    "priority_source": "HTTP API Override"
  }
}
```

#### 响应字段说明
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `status` | `string` | 执行状态，固定为 `"success"` |
| `user_info` | `object` | 当前最新的全量用户信息对象 |
| `user_info.areaName` | `string` | 传入保存的地区名称 |
| `user_info.effective_city` | `string` | 当前系统实际成功生效的聚焦城市/地区名称 |
| `user_info.priority_source` | `string` | 决策来源，此处固定为 `"HTTP API Override"` |
