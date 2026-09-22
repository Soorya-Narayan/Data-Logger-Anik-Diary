"""
PLC Client Factory package.
Instantiates either MockPLCClient or LivePLCClient based on config['plc']['mode'].
"""

import logging
from typing import Dict, Any

from src.plc.base import BasePLCClient
from src.plc.mock_client import MockPLCClient
from src.plc.live_client import LivePLCClient

logger = logging.getLogger("PLCFactory")


def get_plc_client(config: Dict[str, Any], tags_config: Dict[str, Any]) -> BasePLCClient:
    """
    Factory function returning the configured PLC client.
    
    Args:
        config: Loaded config.yaml dictionary
        tags_config: Loaded tags.json dictionary
        
    Returns:
        BasePLCClient instance (MockPLCClient or LivePLCClient)
    """
    mode = config.get("plc", {}).get("mode", "mock").strip().lower()

    if mode == "live":
        logger.info("Initializing LIVE PLC Client (Allen-Bradley Micro850 @ %s)", config.get("plc", {}).get("ip"))
        return LivePLCClient(config=config, tags_config=tags_config)
    elif mode == "mock":
        logger.info("Initializing MOCK PLC Client (PHE-3 SCADA Simulator)")
        return MockPLCClient(config=config)
    else:
        logger.warning("Unrecognized PLC mode '%s'. Defaulting to MockPLCClient.", mode)
        return MockPLCClient(config=config)
