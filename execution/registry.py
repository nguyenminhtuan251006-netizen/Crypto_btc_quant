"""
Strategy Registry with Automatic Auto-Discovery
=================================================
Central registry allowing dynamic registration and automatic auto-discovery of all strategies.
When you create a new strategy (e.g. chien_thuat_4 in chien_thuat/), the system automatically
discovers it and makes it available for 24/7 background execution!
"""
import os
import glob
import importlib
from typing import Dict, Type
from execution.strategy_interface import BaseStrategy
from execution.adapters.strategy_1 import Strategy1Adapter
from execution.adapters.strategy_3 import Strategy3Adapter
from execution.adapters.strategy_4 import Strategy4Adapter
from execution.adapters.strategy_5 import Strategy5Adapter

STRATEGY_MAP: Dict[str, Type[BaseStrategy]] = {
    "chien_thuat_1": Strategy1Adapter,
    "strategy_1": Strategy1Adapter,
    "chien_thuat_3": Strategy3Adapter,
    "strategy_3": Strategy3Adapter,
    "chien_thuat_4": Strategy4Adapter,
    "strategy_4": Strategy4Adapter,
    "chien_thuat_5": Strategy5Adapter,
    "strategy_5": Strategy5Adapter,
}

def auto_discover_strategies():
    """
    Automatically scans chien_thuat/ directory and execution/adapters/
    to register any new strategy without manual configuration.
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chien_thuat_dir = os.path.join(base_dir, "chien_thuat")
    adapters_dir = os.path.join(base_dir, "execution", "adapters")

    # 1. Check adapters directory
    for adapter_file in glob.glob(os.path.join(adapters_dir, "*.py")):
        fname = os.path.basename(adapter_file)
        if fname.startswith("__"):
            continue
        mod_name = fname[:-3]
        try:
            mod = importlib.import_module(f"execution.adapters.{mod_name}")
            for attr in dir(mod):
                obj = getattr(mod, attr)
                if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                    strat_instance = obj()
                    STRATEGY_MAP[strat_instance.name.lower()] = obj
                    if "_" in strat_instance.name:
                        # Also register alias e.g. strategy_4 for chien_thuat_4
                        alias = strat_instance.name.replace("chien_thuat_", "strategy_")
                        STRATEGY_MAP[alias.lower()] = obj
        except Exception:
            pass

    # 2. Check chien_thuat subdirectories for new strategies
    if os.path.exists(chien_thuat_dir):
        for entry in os.listdir(chien_thuat_dir):
            full_path = os.path.join(chien_thuat_dir, entry)
            if os.path.isdir(full_path) and not entry.startswith((".", "_")):
                strat_name = entry.lower()
                # If not registered yet, check if it has a strategy.py
                if strat_name not in STRATEGY_MAP:
                    strat_py = os.path.join(full_path, "strategy.py")
                    if os.path.exists(strat_py):
                        try:
                            spec = importlib.util.spec_from_file_location(f"chien_thuat.{entry}.strategy", strat_py)
                            mod = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(mod)
                            for attr in dir(mod):
                                obj = getattr(mod, attr)
                                if isinstance(obj, type) and issubclass(obj, BaseStrategy) and obj is not BaseStrategy:
                                    STRATEGY_MAP[strat_name] = obj
                        except Exception:
                            pass


def register_strategy(name: str, strategy_cls: Type[BaseStrategy]):
    """Register a new strategy class explicitly to the system."""
    STRATEGY_MAP[name.lower()] = strategy_cls


def get_strategy(name: str) -> BaseStrategy:
    """Retrieve and instantiate a strategy by name (with auto-discovery)."""
    auto_discover_strategies()
    name_clean = name.lower().strip()
    if name_clean not in STRATEGY_MAP:
        available = ", ".join(list_available_strategies())
        raise ValueError(f"Chiến thuật '{name}' chưa được tìm thấy. Danh sách chiến thuật sẵn sàng: {available}")
    
    strat = STRATEGY_MAP[name_clean]()
    strat.initialize()
    return strat


def list_available_strategies() -> list[str]:
    """List all registered and auto-discovered strategies."""
    auto_discover_strategies()
    return sorted(list(set(STRATEGY_MAP.keys())))
