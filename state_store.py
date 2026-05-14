#!/usr/bin/env python3

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

def utc_now_iso() -> str:
		return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def iso_to_dt(iso: str) -> datetime:
		# expects e.g. 2026-01-19T10:00:00+00:00
		return datetime.fromisoformat(iso)

class JsonStateStore:
		"""
		Stores:
			- column presets per endpoint
			- incremental watermark per endpoint (last successful run timestamp)
			- scheduler config
		"""
		def __init__(self, path: str):
				self.path = path
				self._lock = threading.Lock()
				os.makedirs(os.path.dirname(path), exist_ok=True)
				if not os.path.exists(path):
						self._write({
								"presets": {},
								"watermarks": {},
								"schedule": {
										"enabled": False,
										"interval_minutes": 720,
										"endpoints": [],
										"incremental": True
								}
						})
					
		def _read(self) -> Dict[str, Any]:
				with open(self.path, "r", encoding="utf-8") as f:
						return json.load(f)
			
		def _write(self, data: Dict[str, Any]) -> None:
				tmp = self.path + ".tmp"
				with open(tmp, "w", encoding="utf-8") as f:
						json.dump(data, f, indent=2)
				os.replace(tmp, self.path)
			
		def get_all(self) -> Dict[str, Any]:
				with self._lock:
						return self._read()
			
		def get_preset(self, endpoint: str) -> Optional[list]:
				with self._lock:
						data = self._read()
						return data.get("presets", {}).get(endpoint)
			
		def set_preset(self, endpoint: str, columns: list) -> None:
				with self._lock:
						data = self._read()
						data.setdefault("presets", {})[endpoint] = columns
						self._write(data)
					
		def get_watermark(self, endpoint: str) -> Optional[str]:
				with self._lock:
						data = self._read()
						return data.get("watermarks", {}).get(endpoint)
			
		def set_watermark_now(self, endpoint: str) -> str:
				with self._lock:
						data = self._read()
						ts = utc_now_iso()
						data.setdefault("watermarks", {})[endpoint] = ts
						self._write(data)
						return ts

		def set_watermark(self, endpoint: str, iso_value: str) -> str:
				"""
				XR-020: explicit-timestamp variant of set_watermark_now.
				Callers pass the run-start timestamp (captured BEFORE any HTTP work) so
				that records modified DURING the run are still picked up next time.
				"""
				with self._lock:
						data = self._read()
						data.setdefault("watermarks", {})[endpoint] = iso_value
						self._write(data)
						return iso_value
			
		def get_schedule(self) -> Dict[str, Any]:
				with self._lock:
						return self._read().get("schedule", {})
			
		def set_schedule(self, schedule: Dict[str, Any]) -> None:
				with self._lock:
						data = self._read()
						data["schedule"] = schedule
						self._write(data)
					