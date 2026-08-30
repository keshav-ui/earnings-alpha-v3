from fastapi.testclient import TestClient
from earnings_alpha.main import app
def test_health_and_paper_position():
    with TestClient(app) as c:
        assert c.get('/health').json()['live_execution'] is False
        event=c.get('/api/events').json()[0]
        pos=c.post('/api/positions',json={'event_id':event['id'],'quantity':1}).json()
        done=c.post(f"/api/positions/{pos['id']}/exit",json={'price':100}).json()
        assert done['exit_reason']=='MANUAL_EXIT'
