from fastapi.testclient import TestClient
from earnings_alpha.main import app
def test_health_and_paper_position():
    with TestClient(app) as c:
        assert c.get('/health').json()['live_execution'] is False
        analysis=c.post('/api/analyze',json={'symbol':'NVDA','session':'after_market','target_pct':.055,'stop_pct':.035})
        assert analysis.status_code==200
        event=analysis.json()['event']
        side='LONG' if event['signal']=='BUY' else 'SHORT'
        if event['signal']=='WAIT':
            event=c.post('/api/analyze',json={'symbol':'AMD','session':'after_market'}).json()['event']
            side='LONG' if event['signal']=='BUY' else 'SHORT'
        pos=c.post('/api/positions',json={'event_id':event['id'],'quantity':1,'side':side}).json()
        done=c.post(f"/api/positions/{pos['id']}/exit",json={'price':100}).json()
        assert done['exit_reason']=='MANUAL_EXIT'

def test_analysis_rejects_bad_symbol():
    with TestClient(app) as c:
        assert c.post('/api/analyze',json={'symbol':'not a ticker!'}).status_code==422

def test_ten_second_monitor_is_transparent_replay_without_credentials():
    with TestClient(app) as c:
        status=c.get('/api/providers').json()
        assert status['poll_interval_seconds']==10 and status['live_execution'] is False
        made=c.post('/api/watchlist',json={'symbol':'AMD','session':'after_market'})
        assert made.status_code==200
        body=made.json()
        assert body['analysis']['source_mode']=='REPLAY'
        assert c.get('/api/watchlist').json()[0]['symbol']=='AMD'
