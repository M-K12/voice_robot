import os
import sys
import time
import numpy as np
from PySide6.QtCore import QThread, Signal, Slot
import sounddevice as sd
import sherpa_onnx
from loguru import logger

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class AudioKwsThread(QThread):
    """
    后台音频采集与唤醒词识别线程
    """
    signal_kws_detected = Signal(str)  # 触发唤醒词, 参数为识别到的关键词
    signal_volume_rms = Signal(float)  # 传递实时 RMS 音量 [0.0 ~ 1.0]，供波形动画使用
    signal_status = Signal(str)        # 状态变更: "loading", "ready", "error"
    signal_audio_pcm = Signal(bytes)    # 传递原始 16kHz PCM 音频数据，供 WebSocket 通话使用
    signal_mic_status = Signal(bool)   # 麦克风工作正常/被禁用状态 (True/False)

    def __init__(self, model_dir: str, keyword: str = "x iǎo ān x iǎo ān @小安小安", parent=None):
        super().__init__(parent)
        self.model_dir = model_dir
        self.keyword = keyword
        self.is_running = False
        self.sample_rate = 16000
        self.last_trigger_time = 0
        # AEC 处理器引用（可选，延迟注入）
        self._aec_processor = None

    def run(self):
        self.is_running = True
        self.signal_status.emit("loading")
        logger.info("[AudioKwsThread] 初始化离线 KWS 唤醒感知引擎...")

        # 1. 解析模型路径与权重文件
        encoder, decoder, joiner, tokens, keywords_file = self._resolve_model_files(self.model_dir)
        if not encoder:
            self.signal_status.emit("error: 未能找到完整的 ONNX 模型文件")
            return

        # 2. 配置与创建 Sherpa-ONNX KeywordSpotter
        try:
            spotter = sherpa_onnx.KeywordSpotter(
                tokens=tokens,
                encoder=encoder,
                decoder=decoder,
                joiner=joiner,
                keywords_file=keywords_file,
                num_threads=2,
                sample_rate=self.sample_rate,
                feature_dim=80,
                max_active_paths=4,
                keywords_score=1.0,
                keywords_threshold=0.2,
                num_trailing_blanks=1,
                provider="cpu",
            )
            stream_kws = spotter.create_stream()
            logger.info("[AudioKwsThread] 唤醒检测组件加载成功！")
            self.signal_status.emit("ready")
        except Exception as e:
            logger.error(f"[AudioKwsThread] 创建 KWS 失败: {e}")
            self.signal_status.emit(f"error: {e}")
            return

        # 3. 音频流回调处理
        def audio_callback(indata, frames, time_info, status):
            if not self.is_running:
                return
            pcm_float = indata.flatten()

            # 计算实时 RMS 音量并发射 (始终发射，保持波形动画正常显示)
            rms = np.sqrt(np.mean(pcm_float ** 2))
            normalized_rms = float(min(1.0, rms * 10))
            self.signal_volume_rms.emit(normalized_rms)

            # 第一层：静音底噪门限 (Noise Gate)
            # 消除设备微小静音底噪帧，平抗安静环境底噪
            if rms < 0.005:
                pcm_int16 = np.zeros(len(pcm_float), dtype=np.int16)
            else:
                pcm_int16 = (np.clip(pcm_float, -1.0, 1.0) * 32767.0).astype(np.int16)

            # 第二层： SpeexDSP AEC 回声消除 (Near-end 处理)
            # 如未安装 speexdsp 或 AEC 处理器未注入，直接透传
            pcm_bytes = pcm_int16.tobytes()
            if self._aec_processor is not None:
                pcm_bytes = self._aec_processor.process_near_end(pcm_bytes)

            # 发射到 WebSocket 上传链路 (经 AEC 消除回声后的纯净 PCM)
            self.signal_audio_pcm.emit(pcm_bytes)

            # 喂给 KWS 关键词流式解码
            # 使用 AEC 处理后的 int16 PCM 转回 float32 嗂给 sherpa-onnx
            pcm_aec = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32767.0
            stream_kws.accept_waveform(self.sample_rate, pcm_aec)

            while spotter.is_ready(stream_kws):
                spotter.decode_stream(stream_kws)
                keyword = spotter.get_result(stream_kws)
                if keyword:
                    now = time.time()
                    # 1.5 秒防抖
                    if now - self.last_trigger_time > 1.5:
                        self.last_trigger_time = now
                        logger.info(f"[AudioKwsThread] 🔥 唤醒词命中: {keyword}")
                        self.signal_kws_detected.emit(str(keyword))
                    spotter.reset_stream(stream_kws)

        # 4. 开启 sounddevice 麦克风流 (多重智能容错与候选设备轮询)
        def create_input_stream(device_idx=None):
            kwargs = {
                "samplerate": self.sample_rate,
                "channels": 1,
                "dtype": "float32",
                "blocksize": 1600,
                "callback": audio_callback,
            }
            if device_idx is not None:
                kwargs["device"] = device_idx
            return sd.InputStream(**kwargs)

        stream = None
        # 4.1 优先尝试系统默认输入设备 (不强制显式传 device 参数)
        try:
            stream = create_input_stream(None)
            logger.info("[AudioKwsThread] 🎤 默认输入设备绑定成功，开启唤醒监听...")
        except Exception as e1:
            logger.warning(f"[AudioKwsThread] 默认输入设备打开失败 ({e1})，启动智能候选设备轮询...")

        # 4.2 若默认失败，优先选择非 Virtual/虚拟声卡的真实物理麦克风并尝试打开
        if stream is None and sd:
            try:
                all_devices = sd.query_devices()
                candidate_indices = []
                for idx, dev in enumerate(all_devices):
                    if dev.get("max_input_channels", 0) > 0:
                        dev_name = str(dev.get("name", "")).lower()
                        # 真实物理麦克风赋予高优先级，排在最前面
                        if not any(k in dev_name for k in ["virtual", "stereo mix", "mfdriver", "mapper"]):
                            candidate_indices.insert(0, idx)
                        else:
                            candidate_indices.append(idx)

                for c_idx in candidate_indices:
                    try:
                        dev_info = all_devices[c_idx]
                        logger.info(f"[AudioKwsThread] 尝试绑定设备 [{c_idx}]: {dev_info.get('name')}")
                        stream = create_input_stream(c_idx)
                        logger.info(f"[AudioKwsThread] 🎤 成功容错绑定到输入设备 [{c_idx}]: {dev_info.get('name')}")
                        break
                    except Exception as try_err:
                        logger.debug(f"[AudioKwsThread] 尝试绑定设备 [{c_idx}] 失败: {try_err}")
            except Exception as scan_err:
                logger.error(f"[AudioKwsThread] 扫描输入设备遇到异常: {scan_err}")

        if stream is None:
            logger.error("[AudioKwsThread] 无法找到任何可正常工作的物理/虚拟麦克风设备")
            self.signal_status.emit("error: 未找到可用麦克风设备")
            self.signal_mic_status.emit(False)
            return

        try:
            with stream:
                logger.info("[AudioKwsThread] 麦克风录音流运行中，持续唤醒监听...")
                self.signal_mic_status.emit(True)
                while self.is_running:
                    self.msleep(50)
        except Exception as e:
            logger.error(f"[AudioKwsThread] 麦克风输入流异常中断: {e}")
            self.signal_status.emit(f"error: 麦克风打不开: {e}")
            self.signal_mic_status.emit(False)

        self.signal_mic_status.emit(False)
        logger.info("[AudioKwsThread] KWS 线程已退出")

    def stop(self):
        self.is_running = False
        self.wait(1000)

    def set_aec_processor(self, aec_processor) -> None:
        """延迟注入 AECProcessor，允许在 KWS 线程启动前后均可绑定。"""
        self._aec_processor = aec_processor
        logger.info(f"[AudioKwsThread] AEC 处理器已绑定: {aec_processor}")

    def _resolve_model_files(self, model_dir: str):
        path = os.path.abspath(model_dir)
        if not os.path.isabs(model_dir):
            path = os.path.join(PROJECT_ROOT, model_dir)
        if not os.path.exists(path):
            return None, None, None, None, None

        tokens = os.path.join(path, "tokens.txt")
        keywords_file = os.path.join(path, "keywords.txt")

        encoders = [f for f in os.listdir(path) if f.startswith("encoder-") and f.endswith(".onnx")]
        decoders = [f for f in os.listdir(path) if f.startswith("decoder-") and f.endswith(".onnx")]
        joiners = [f for f in os.listdir(path) if f.startswith("joiner-") and f.endswith(".onnx")]

        if not (encoders and decoders and joiners):
            return None, None, None, None, None

        def select_best(files, pref_chunk="chunk-16"):
            non_int8 = [f for f in files if "int8" not in f]
            target_list = non_int8 if non_int8 else files
            matched = [f for f in target_list if pref_chunk in f]
            if matched:
                return os.path.join(path, matched[0])
            return os.path.join(path, target_list[0])

        enc = select_best(encoders)
        dec = select_best(decoders)
        joi = select_best(joiners)

        return enc, dec, joi, tokens, keywords_file
