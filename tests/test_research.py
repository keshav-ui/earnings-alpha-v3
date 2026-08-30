from datetime import datetime, timedelta, timezone
from earnings_alpha.research import Bar, backtest, features
def b(minutes,last,bid=None,ask=None):
    return Bar(datetime(2026,8,28,20,0,tzinfo=timezone.utc)+timedelta(minutes=minutes),bid or last-.05,ask or last+.05,last,100)
def test_target_uses_executable_bid():
    r=backtest([b(0,100),b(1,106)],target=.055,stop=.035,slippage_bps=0)
    assert r.outcome=="TARGET" and r.return_pct>.055
def test_stop_uses_executable_bid():
    r=backtest([b(0,100),b(1,96)],target=.055,stop=.035,slippage_bps=0)
    assert r.outcome=="STOP_LOSS"
def test_features_no_future_argument():
    f=features([b(0,100),b(1,101)],{"eps_surprise":.1})
    assert f["eps_surprise"]==.1 and f["volume"]==200
