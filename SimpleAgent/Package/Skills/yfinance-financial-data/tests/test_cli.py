import importlib.util
import json
import pathlib
import subprocess
import sys
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / 'scripts' / 'yf_query.py'
spec = importlib.util.spec_from_file_location('yf_query', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class FakeTicker:
    info = {'longName': 'Test', 'marketCap': 100, 'returnOnEquity': 0.24}
    options = ['2027-01-15']
    dividends = [1, 2]
    def history(self, **kw):
        return m.pd.DataFrame([{'Open': 1, 'Close': 2}])

class TestCLI(unittest.TestCase):
    def test_shares_preserves_source_dates_and_limits_most_recent_first(self):
        if m.pd is None:
            self.skipTest('pandas unavailable')
        class SharesTicker:
            def get_shares_full(self):
                return m.pd.Series([10, 30, 20, 50], index=[
                    m.pd.Timestamp('2024-01-01'), m.pd.Timestamp('2024-03-01'),
                    m.pd.Timestamp('2024-02-01'), m.pd.NaT,
                ])
        args = m.parser().parse_args(['shares', '2330.TW', '--limit', '2'])
        data, warnings = m.query(SharesTicker(), args)
        self.assertEqual(data['shares'], [
            {'index': '2024-03-01', 'value': 30}, {'index': '2024-02-01', 'value': 20},
        ])
        self.assertEqual(data['total_rows'], 3)
        self.assertEqual(data['returned_rows'], 2)
        self.assertTrue(data['truncated'])
        self.assertTrue(any('valid source date' in warning for warning in warnings))

    def test_shares_without_dated_data_is_unavailable(self):
        if m.pd is None:
            self.skipTest('pandas unavailable')
        class SharesTicker:
            def get_shares_full(self):
                return m.pd.Series([10], index=[1])
        args = m.parser().parse_args(['shares', '2330.TW'])
        data, warnings = m.query(SharesTicker(), args)
        self.assertEqual(data['shares'], [])
        self.assertTrue(any('unavailable' in warning for warning in warnings))

    def test_dictionary(self):
        self.assertTrue(len(m.field_mapping()) >= 150)
        self.assertIsNotNone(m.translate_key('marketCap'))

    def test_info_missing_field(self):
        args = m.parser().parse_args(['info', 'AAPL', '--fields', 'longName,missing'])
        data, warnings = m.query(FakeTicker(), args)
        self.assertIn('longName', data)
        self.assertNotIn('missing', data)
        self.assertTrue(warnings)

    def test_history_defaults_to_all(self):
        args = m.parser().parse_args(['history', 'AAPL', '--period', '1y', '--interval', '1d'])
        self.assertEqual(args.limit, 0)
        if m.pd is not None:
            class LongTicker:
                def history(self, **kw):
                    return m.pd.DataFrame({'Close': list(range(250))})
            data, _ = m.query(LongTicker(), args)
            self.assertEqual(data['total_rows'], 250)
            self.assertEqual(data['returned_rows'], 250)
            self.assertFalse(data['truncated'])
            self.assertEqual(len(data['prices']['records']), 250)

    def test_history_explicit_limit(self):
        args = m.parser().parse_args(['history', 'AAPL', '--limit', '10'])
        if m.pd is not None:
            class LongTicker:
                def history(self, **kw):
                    return m.pd.DataFrame({'Close': list(range(250))})
            data, _ = m.query(LongTicker(), args)
            self.assertTrue(data['truncated'])
            self.assertEqual(data['returned_rows'], 10)

    def test_help(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('history', result.stdout)

    def test_fields_json(self):
        result = subprocess.run([sys.executable, str(SCRIPT), 'fields', '--search', '市值'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertGreater(json.loads(result.stdout)['count'], 0)

    def test_serialization(self):
        if m.pd:
            df = m.pd.DataFrame({'a':[2,3]}, index=['x','y'])
            self.assertEqual(m.clean(df)['records'][0]['a'], 2)

if __name__ == '__main__': unittest.main()
