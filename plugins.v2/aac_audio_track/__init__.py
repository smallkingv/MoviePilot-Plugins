import os
import subprocess
import json
import asyncio
from typing import Optional, Dict, Any
from pathlib import Path

from app.core.event import eventmanager, Event
from app.schemas.types import EventType
from app.log import logger
from app.plugins import _PluginBase


class AacAudioTrack(_PluginBase):
    plugin_name = "AAC音轨添加器"
    plugin_version = "1.0.0"
    plugin_description = "检测整理后的视频文件，如果没有AAC音轨则自动添加AAC stereo音轨"
    plugin_author = "Your Name"
    plugin_icon = "music_note.png"
    plugin_order = 100

    def init_plugin(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._enabled = self._config.get("enabled", False)
        self._watch_paths = self._config.get("watch_paths", [])
        self._ffmpeg_path = self._config.get("ffmpeg_path", "ffmpeg")
        self._aac_bitrate = self._config.get("aac_bitrate", "192k")
        self._processed_files = set()
        
        if self._enabled:
            logger.info(f"{self.plugin_name} 插件已启用")
            logger.info(f"监控路径: {self._watch_paths}")
        else:
            logger.info(f"{self.plugin_name} 插件未启用")

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> Optional[Dict[str, Any]]:
        pass

    def get_api(self) -> Optional[Dict[str, Any]]:
        pass

    def get_form(self) -> Optional[Dict[str, Any]]:
        return {
            "enabled": {
                "title": "启用插件",
                "required": False,
                "type": "switch",
                "default": False
            },
            "watch_paths": {
                "title": "监控路径",
                "required": True,
                "type": "list-string",
                "default": [],
                "tooltip": "需要监控的视频文件目录，支持多个路径"
            },
            "ffmpeg_path": {
                "title": "FFmpeg路径",
                "required": False,
                "type": "string",
                "default": "ffmpeg",
                "tooltip": "FFmpeg可执行文件路径，默认使用系统PATH中的ffmpeg"
            },
            "aac_bitrate": {
                "title": "AAC比特率",
                "required": False,
                "type": "string",
                "default": "192k",
                "tooltip": "AAC音轨的比特率，如128k、192k、256k等"
            }
        }

    def stop_service(self):
        pass

    def _is_video_file(self, filepath: str) -> bool:
        video_extensions = {'.mp4', '.mkv', '.avi', '.mov', '.flv', '.wmv', '.webm', '.m4v'}
        return Path(filepath).suffix.lower() in video_extensions

    def _check_aac_audio(self, filepath: str) -> bool:
        try:
            cmd = [
                self._ffmpeg_path,
                '-i', filepath,
                '-hide_banner',
                '-loglevel', 'error',
                '-select_streams', 'a',
                '-show_entries', 'stream=codec_name',
                '-of', 'json',
                '-'
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                logger.error(f"获取音轨信息失败: {filepath}")
                return False
            
            try:
                streams_info = json.loads(result.stdout)
                streams = streams_info.get('streams', [])
                
                for stream in streams:
                    codec_name = stream.get('codec_name', '').lower()
                    if 'aac' in codec_name:
                        logger.info(f"视频已包含AAC音轨: {filepath}")
                        return True
                
                return False
            except json.JSONDecodeError:
                logger.error(f"解析音轨信息JSON失败: {filepath}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"获取音轨信息超时: {filepath}")
            return False
        except Exception as e:
            logger.error(f"检查AAC音轨时发生错误: {filepath}, 错误: {str(e)}")
            return False

    def _add_aac_audio(self, filepath: str) -> bool:
        try:
            temp_file = filepath + '.temp'
            
            cmd = [
                self._ffmpeg_path,
                '-i', filepath,
                '-c:v', 'copy',
                '-c:a', 'aac',
                '-b:a', self._aac_bitrate,
                '-ac', '2',
                '-map', '0:v',
                '-map', '0:a?',
                '-c:s', 'copy',
                '-map', '0:s?',
                '-y',
                temp_file
            ]
            
            logger.info(f"开始添加AAC音轨: {filepath}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600
            )
            
            if result.returncode != 0:
                logger.error(f"添加AAC音轨失败: {filepath}")
                logger.error(f"错误信息: {result.stderr}")
                return False
            
            if os.path.exists(temp_file):
                original_size = os.path.getsize(filepath)
                new_size = os.path.getsize(temp_file)
                
                os.remove(filepath)
                os.rename(temp_file, filepath)
                
                logger.info(f"成功添加AAC音轨: {filepath}")
                logger.info(f"文件大小变化: {original_size / (1024*1024):.2f}MB -> {new_size / (1024*1024):.2f}MB")
                return True
            else:
                logger.error(f"临时文件未创建: {temp_file}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"添加AAC音轨超时: {filepath}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False
        except Exception as e:
            logger.error(f"添加AAC音轨时发生错误: {filepath}, 错误: {str(e)}")
            if os.path.exists(temp_file):
                os.remove(temp_file)
            return False

    def _process_video_file(self, filepath: str):
        if not self._enabled:
            return
        
        if filepath in self._processed_files:
            return
        
        if not self._is_video_file(filepath):
            return
        
        if not os.path.exists(filepath):
            logger.warning(f"文件不存在: {filepath}")
            return
        
        logger.info(f"开始处理视频文件: {filepath}")
        
        if self._check_aac_audio(filepath):
            self._processed_files.add(filepath)
            return
        
        if self._add_aac_audio(filepath):
            self._processed_files.add(filepath)
        else:
            logger.error(f"处理失败: {filepath}")

    def _scan_directory(self, directory: str):
        try:
            for root, dirs, files in os.walk(directory):
                for file in files:
                    filepath = os.path.join(root, file)
                    self._process_video_file(filepath)
        except Exception as e:
            logger.error(f"扫描目录时发生错误: {directory}, 错误: {str(e)}")

    @eventmanager.register(EventType.TransferComplete)
    async def handle_transfer_complete(self, event: Event):
        if not self._enabled:
            return
        
        event_data = event.event_data
        logger.info(f"收到转移完成事件: {event_data}")
        
        transfer_path = event_data.get('path', '')
        target_path = event_data.get('target_path', '')
        
        paths_to_scan = []
        if transfer_path and os.path.exists(transfer_path):
            paths_to_scan.append(transfer_path)
        if target_path and os.path.exists(target_path):
            paths_to_scan.append(target_path)
        
        for path in paths_to_scan:
            if os.path.isfile(path):
                self._process_video_file(path)
            elif os.path.isdir(path):
                self._scan_directory(path)

    async def manual_scan(self):
        if not self._enabled:
            logger.warning("插件未启用，无法执行手动扫描")
            return
        
        logger.info("开始手动扫描监控路径")
        
        for watch_path in self._watch_paths:
            if os.path.exists(watch_path):
                if os.path.isfile(watch_path):
                    self._process_video_file(watch_path)
                elif os.path.isdir(watch_path):
                    self._scan_directory(watch_path)
            else:
                logger.warning(f"监控路径不存在: {watch_path}")
        
        logger.info("手动扫描完成")
