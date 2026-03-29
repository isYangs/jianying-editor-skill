"""
TTS 音色列表探测脚本

用已知音色逐一探测 SAMI API，返回有效的 speaker_id 列表
"""

import asyncio
import csv
import json
import os
import ssl
import websockets


APP_KEY = "IZjhUeAYwP"
APP_ID = "3704"

# 已知的音色列表（从 tts_speakers.csv）
KNOWN_SPEAKERS = [
    "zh_female_xiaopengyou", "zh_male_iclvop_zhangjinxiangnanzhu", "BV408_streaming",
    "zh_male_iclvop_xiaolinkepu", "zh_male_sunwukong_clone2", "zh_male_xionger_stream_gpu",
    "BV411_streaming", "ICL_zh_female_basidigua2", "BV701_streaming", "BV005_streaming",
    "zh_female_yingtiannini", "zh_female_inspirational", "zh_male_zhengtaikp", "BV001_fast_streaming",
    "BV414_streaming", "BV433_streaming", "zh_male_novel_clone2", "zh_female_ziwei",
    "zh_male_silang_stream_gpu", "BV021_streaming", "BV426_streaming", "ICL_zh_female_jilupianxq2",
    "BV405_streaming", "zh_male_iclvop_chenxuanad", "zh_female_iclvop_zdjxsusuyule",
    "ICL_zh_female_manbo_jianying", "BV504_streaming", "zh_female_iclvop_gzycwxiangling",
    "zh_female_peiqi", "BV056_streaming", "zh_male_iclvop_miaojijsqinggan",
    "ICL_zh_female_pangbaiyw", "zh_male_taiwan_clone2", "zh_female_iclvop_zdjxsusujiaomai",
    "BV213_streaming", "zh_female_iclvop_zdjxsusukeli", "BV430_streaming", "BV409_streaming",
    "BV064_streaming", "zh_female_iclvop_zdjxsmmguwen", "en_female_kat_clone2",
    "zh_female_aoyunliuyuxi", "BV144_streaming", "ICL_zh_male_qinggandiantai",
    "zh_female_ganmaodianyin", "BV403_streaming",
]


def get_jy_local_config():
    """获取剪映本地配置"""
    import platform
    import re

    system = platform.system()

    if system == "Windows":
        local_app_data = os.getenv("LOCALAPPDATA")
        if not local_app_data:
            return "1259406410923456", "1259406411435456"
        jy_user_data = os.path.join(local_app_data, r"JianyingPro\User Data")
        ttnet_path = os.path.join(jy_user_data, r"TTNet\tt_net_config.config")
    elif system == "Darwin":
        home = os.path.expanduser("~")
        jy_user_data = os.path.join(home, "Library/Application Support/JianyingPro/User Data")
        ttnet_path = os.path.join(jy_user_data, "TTNet/tt_net_config.config")
    else:
        return "1259406410923456", "1259406411435456"

    if os.path.exists(ttnet_path):
        try:
            with open(ttnet_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            m = re.search(r"device_id&#\*(\d+)", content)
            if m:
                return m.group(1), "1259406411435456"
        except Exception:
            pass

    return "1259406410923456", "1259406411435456"


async def test_speaker(speaker_id: str, dev_id: str, iid: str) -> bool:
    """测试单个音色是否有效（独立连接）"""
    ws_url = f"wss://sami.bytedance.com/internal/api/v2/ws?device_id={dev_id}&iid={iid}"
    headers = {
        "sdk-version": "2",
        "aid": "3704",
        "passport-auth": "asgw",
        "User-Agent": "Cronet/TTNetVersion:3024dcd7 2023-10-18 QuicVersion:4bf243e0 2023-04-17"
    }
    
    task_id = f"test_{os.urandom(4).hex()}"
    msg = {
        "app_id": APP_ID,
        "appkey": APP_KEY,
        "event": "StartTask",
        "namespace": "TTS",
        "task_id": task_id,
        "message_id": task_id + "_0",
        "payload": json.dumps({
            "text": "测试",
            "speaker": speaker_id,
            "audio_config": {"format": "ogg_opus", "sample_rate": 24000, "bit_rate": 64000}
        }, ensure_ascii=False, separators=(",", ":")),
    }
    
    try:
        async with websockets.connect(ws_url, additional_headers=headers, ssl=ssl.create_default_context(), open_timeout=20) as ws:
            await ws.send(json.dumps(msg, ensure_ascii=False, separators=(",", ":")))
            
            # 收集所有响应直到收到音频数据或超时
            while True:
                try:
                    resp_raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    if isinstance(resp_raw, str):
                        resp = json.loads(resp_raw)
                        event = resp.get("event")
                        if event == "TaskFinished":
                            return True  # 成功
                        elif event == "TaskFailed":
                            code = resp.get("status_code")
                            print(f"(code={code})", end="")
                            return False  # 失败
                    elif isinstance(resp_raw, bytes) and len(resp_raw) > 100:
                        return True  # 收到音频数据
                except asyncio.TimeoutError:
                    return False
    except Exception as e:
        print(f"(error: {e})", end="")
        return False


async def probe_all_speakers():
    """探测所有已知音色"""
    dev_id, iid = get_jy_local_config()
    ws_url = f"wss://sami.bytedance.com/internal/api/v2/ws?device_id={dev_id}&iid={iid}"

    headers = {
        "sdk-version": "2",
        "aid": "3704",
        "passport-auth": "asgw",
        "User-Agent": "Cronet/TTNetVersion:3024dcd7 2023-10-18 QuicVersion:4bf243e0 2023-04-17"
    }

    print(f"[*] 连接 SAMI API... dev_id={dev_id}, iid={iid}")
    print(f"[*] 开始探测 {len(KNOWN_SPEAKERS)} 个已知音色...\n")

    valid_speakers = []
    invalid_speakers = []

    for i, speaker in enumerate(KNOWN_SPEAKERS):
        print(f"[*] 测试 [{i+1}/{len(KNOWN_SPEAKERS)}] {speaker}...", end=" ", flush=True)
        is_valid = await test_speaker(speaker, dev_id, iid)
        if is_valid:
            print("✅ 有效")
            valid_speakers.append(speaker)
        else:
            print("❌ 无效")
            invalid_speakers.append(speaker)
        
        await asyncio.sleep(0.3)  # 避免请求过快
        print(f"\n✅ 有效音色 ({len(valid_speakers)}):")
        for s in valid_speakers:
            print(f"  - {s}")

    if invalid_speakers:
        print(f"\n❌ 无效音色 ({len(invalid_speakers)}):")
        for s in invalid_speakers:
            print(f"  - {s}")

    return valid_speakers, invalid_speakers


if __name__ == "__main__":
    asyncio.run(probe_all_speakers())
