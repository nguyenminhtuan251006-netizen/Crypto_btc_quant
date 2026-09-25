"""Offline regressions for strategies 4/5. No exchange calls or credentials."""
import tempfile
import unittest
import io
from contextlib import ExitStack, redirect_stdout
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

from execution.afcx_client import AFCXClient
from execution.afcx_order_reconciler import OrderReconciler
from execution.afcx_order_registry import OrderRegistry
from execution.afcx_risk_manager import RiskManager
from chien_thuat.chien_thuat_4.src.execution_universe import UniverseManager
from chien_thuat.chien_thuat_4.src.session_manager import SessionManager, ASIA_PROFILE
from chien_thuat.chien_thuat_4.src.cross_sectional_ranker import CrossSectionalRanker
from execution.adapters.strategy_4 import Strategy4Adapter
from execution.adapters.strategy_5 import Strategy5Adapter


class SafetyTests(unittest.TestCase):
    def exercise_daemon(self, reject_close=False, strategy_name='chien_thuat_5'):
        import pandas as pd
        import execution.afcx_daemon as daemon
        from execution.strategy_interface import StrategyDecision

        class Exchange:
            def __init__(self):
                self.stage = -1
                self.qty = 0
                self.events = []
                self.orders = []
                self.algos = []

            def get(self, endpoint, params=None):
                if endpoint == '/fapi/v2/account':
                    self.stage += 1
                    if self.stage >= (3 if reject_close else 4):
                        daemon.running = False
                        raise RuntimeError('End of simulated market')
                    return dict(totalMarginBalance=1000, availableBalance=1000)
                if endpoint == '/fapi/v2/positionRisk':
                    return [dict(symbol='ETHUSDT', positionAmt=self.qty, entryPrice=100, unRealizedProfit=0)] if self.qty else []
                if endpoint == '/fapi/v1/openOrders':
                    return self.orders
                if endpoint == '/fapi/v1/openAlgoOrders':
                    return self.algos
                if endpoint == '/fapi/v1/income':
                    return [dict(incomeType='REALIZED_PNL', income='-0.1')]
                raise AssertionError(endpoint)

            def init_account_settings(self, *args, **kwargs):
                pass

            def place_market_order(self, symbol, side, qty, reduce_only=False, client_order_id=None):
                self.events.append(('close' if reduce_only else 'entry', self.stage))
                if reduce_only and reject_close:
                    raise RuntimeError('Close rejected')
                self.qty = 0 if reduce_only else qty
                return dict(status='FILLED', orderId=1, avgPrice='100', executedQty=qty)

            def post(self, endpoint, params):
                if endpoint.endswith('algoOrder'):
                    self.algos = [dict(algoId=2)]
                    self.events.append(('stop', self.stage))
                    return self.algos[0]
                self.orders = [dict(orderId=3)]
                self.events.append(('tp', self.stage))
                return self.orders[0]

            def delete(self, endpoint, params):
                self.events.append(('cancel', self.stage))
                return {}

        exchange = Exchange()
        strategy = SimpleNamespace(name=strategy_name, symbol='ETHUSDT', leverage=10,
            stop_loss_pct=0.006, take_profit_pct=0.012, enable_trailing=True, wide_tp_pct=0.08,
            cached_ranking=[dict(symbol='ETHUSDT', final_score=-1)], last_trade_close_time=0,
            analyze=lambda data: StrategyDecision(signal=1 if exchange.stage == 1 else 0,
                confidence=0.8, reason='simulation', sl_pct=0.01,
                extra_metrics={'selected_symbol': 'ETHUSDT', 'candidate': {'current_price': 100}}))
        universe = UniverseManager()
        universe.metadata_cache['ETHUSDT'].update(market_min_qty=0.001, market_max_qty=100,
            min_notional=5, market_step_size=0.001)
        universe.verified_symbols.add('ETHUSDT')
        universe.refresh_exchange_metadata = Mock()
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for target, value in [('workspace_dir', directory), ('running', True),
                ('AFCXClient', lambda *a, **k: exchange), ('get_strategy', lambda name: strategy),
                ('load_credentials', lambda **k: ('unused', 'unused')),
                ('UniverseManager', lambda: universe),
                ('fetch_recent_candles', lambda *a, **k: pd.DataFrame({'close': [100]})),
                ('fetch_orderbook_l2', lambda *a, **k: {'bids': [['100', '1']], 'asks': [['100', '1']]}),
                ('fetch_recent_trades', lambda *a, **k: [])]:
                stack.enter_context(patch.object(daemon, target, value))
            stack.enter_context(patch('time.sleep'))
            stack.enter_context(redirect_stdout(io.StringIO()))
            daemon.run_daemon(strategy_name, poll_interval=1, mode='demo')
            registry = OrderRegistry(str(Path(directory) / f'logs/trade_registry_{strategy_name}_demo.json'))
            return exchange.events, registry.data

    def test_full_entry_protection_exit_and_settlement(self):
        events, registry = self.exercise_daemon()
        self.assertEqual(events[:3], [('entry', 1), ('stop', 1), ('tp', 1)])
        self.assertIn(('close', 2), events)
        self.assertTrue(all(stage == 3 for action, stage in events if action == 'cancel'))
        self.assertIsNone(registry['active_trade'])
        self.assertEqual(registry['closed_trades'][0]['net_pnl'], -0.1)

    def test_strategy4_qualified_signal_reaches_exchange(self):
        # Regression: a valid AFCX signal previously crashed on the undefined
        # fetch_orderbook name before the market entry was submitted.
        events, registry = self.exercise_daemon(strategy_name='chien_thuat_4')
        self.assertEqual(events[:3], [('entry', 1), ('stop', 1), ('tp', 1)])
        self.assertIsNone(registry['active_trade'])

    def test_rejected_close_preserves_ownership_and_protection(self):
        events, registry = self.exercise_daemon(reject_close=True)
        self.assertIsNotNone(registry['active_trade'])
        self.assertFalse(any(action == 'cancel' for action, _ in events))

    def test_small_account_never_forces_notional_floor(self):
        with tempfile.TemporaryDirectory() as directory:
            risk = RiskManager(state_file=str(Path(directory) / 'risk.json'), max_leverage=10)
            qty, notional, _ = risk.calculate_position_size(8.55, 0.015, 100, min_notional=15)
            self.assertLess(notional, 15)
            self.assertLessEqual(qty * 100 * (0.015 + 0.0014), 8.55 * 0.005 + 1e-12)

    def test_precision_uses_steps_and_does_not_round_up(self):
        universe = UniverseManager()
        universe.metadata_cache['TEST'] = dict(tick_size=0.25, step_size=0.05)
        self.assertEqual(universe.quantize_price('TEST', 10.13), 10.25)
        self.assertEqual(universe.quantize_qty('TEST', 0.129), 0.1)
        self.assertEqual(universe.quantize_qty('TEST', 0.01), 0)
        with self.assertRaises(ValueError):
            universe.validate_entry('TEST', 0.1, 10)

    def test_cached_scan_is_not_confirmation(self):
        manager = SessionManager()
        self.assertFalse(manager.check_persistence_gate('ETHUSDT', 1, 1000, ASIA_PROFILE)[0])
        self.assertFalse(manager.check_persistence_gate('ETHUSDT', 1, 1000, ASIA_PROFILE)[0])
        self.assertTrue(manager.check_persistence_gate('ETHUSDT', 1, 1121, ASIA_PROFILE)[0])

    def test_cooldown_reaches_engine(self):
        for adapter, engine_name in [(Strategy4Adapter(), 'afcx'), (Strategy5Adapter(), 'strat')]:
            adapter.last_trade_close_time = 123
            self.assertEqual(getattr(adapter, engine_name).last_trade_close_time, 123)

    def test_failed_stop_replacement_keeps_existing_stop(self):
        client = Mock()
        client.post.side_effect = RuntimeError('rejected')
        with patch('execution.afcx_order_reconciler.time.sleep'), self.assertRaises(RuntimeError):
            OrderReconciler(client).update_stop_loss(1, 1, 90, old_order_id=12)
        client.delete.assert_not_called()

    def test_stop_confirmation_precedes_targeted_cancel(self):
        events = []
        client = Mock()
        client.post.side_effect = lambda *args: events.append('new') or {'algoId': 13}
        client.delete.side_effect = lambda *args: events.append(args[1]['algoId']) or {}
        with patch('execution.afcx_order_reconciler.time.sleep'):
            OrderReconciler(client).update_stop_loss(1, 1, 90, old_order_id=12)
        self.assertEqual(events, ['new', 12])

    def test_close_is_reduce_only(self):
        client = AFCXClient('unused', 'unused', 'https://invalid')
        client.post = Mock(return_value={'orderId': 3})
        client.place_market_order('ETHUSDT', 'SELL', 1, reduce_only=True)
        self.assertEqual(client.post.call_args.args[1]['reduceOnly'], 'true')

    def test_exchange_error_is_not_success(self):
        response = Mock()
        response.json.return_value = {'code': -2010, 'msg': 'rejected'}
        with patch('execution.afcx_client.requests.request', return_value=response), self.assertRaises(RuntimeError):
            AFCXClient('unused', 'unused', 'https://invalid').get('/test')

    def test_settlement_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            risk = RiskManager(state_file=str(Path(directory) / 'risk.json'))
            risk.record_trade_outcome(-0.1, 8.45, trade_id='one')
            risk.record_trade_outcome(-0.1, 8.45, trade_id='one')
            self.assertEqual(risk.state['consecutive_losses'], 1)

    def test_registry_restart_preserves_stop_and_pending_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = str(Path(directory) / 'registry.json')
            registry = OrderRegistry(filename)
            registry.register_new_trade('ASIA', 'ETHUSDT', 'BUY', 1, 100, 108, 99)
            registry.update_active_state(entry_pending=True, sl_price=101, highest_price=103)
            restored = OrderRegistry(filename).get_active_trade()
            self.assertEqual(restored['sl_price'], 101)
            self.assertTrue(restored['entry_pending'])

    def test_relative_winner_cannot_long_negative_momentum(self):
        candidate = dict(abs_score=2, final_score=2, direction=1, momentum_raw=-0.01,
                         symbol='ETHUSDT', consensus_count=6, atr_pct=0.01)
        passed, _, reason = CrossSectionalRanker().evaluate_top_candidate([candidate, dict(abs_score=1)])
        self.assertFalse(passed)
        self.assertIn('ABSOLUTE_DIRECTION', reason)


if __name__ == '__main__':
    unittest.main()
