#!/usr/bin/env python3

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

def setup_logging(log_path: str, level: int = logging.INFO, name: str = "xero_runner") -> logging.Logger:
	"""
	Minimal, crash-safe logging:
	- Rotating file in data/
	- Console logging for dev
	Safe to call multiple times (won't duplicate handlers).
	"""
	logger = logging.getLogger(name)
	logger.setLevel(level)
	
	if getattr(logger, "_xero_runner_configured", False):
		return logger
	
	os.makedirs(os.path.dirname(log_path), exist_ok=True)
	
	fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
	
	file_handler = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
	file_handler.setFormatter(fmt)
	file_handler.setLevel(level)
	
	console = logging.StreamHandler()
	console.setFormatter(fmt)
	console.setLevel(level)
	
	logger.addHandler(file_handler)
	logger.addHandler(console)
	logger.propagate = False
	
	logger._xero_runner_configured = True  # type: ignore[attr-defined]
	return logger
