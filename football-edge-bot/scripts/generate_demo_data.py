import random
from datetime import datetime, timedelta
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.db import Base, engine, SessionLocal
from backend.app.models import Team, Fixture, OddsSnapshot, BankrollEvent

Base.metadata.create_all(bind=engine)
db=SessionLocal()
random.seed(42)
teams=[]
for i,name in enumerate([
    'Arsenal','Liverpool','Manchester City','Chelsea','Manchester United','Newcastle United',
    'Tottenham','Aston Villa','Brighton','West Ham','Crystal Palace','Everton','Fulham','Brentford',
    'Wolves','Nottingham Forest','Leicester City','Bournemouth','Aston Villa B','Leeds United'
], start=1):
    t=Team(provider_id=10000+i,name=name,country='England')
    db.add(t); teams.append(t)
db.flush()
base=datetime.utcnow()-timedelta(days=420)
for i in range(320):
    h,a=random.sample(teams,2)
    kickoff=base+timedelta(hours=i*32)
    hg=max(0,int(random.expovariate(1/1.35)))
    ag=max(0,int(random.expovariate(1/1.05)))
    if i>=300:
        hg=ag=None; status='NS'
    else:
        status='FT'
    f=Fixture(provider_id=200000+i,league_id=39,season=2025,kickoff=kickoff,status=status,home_team_id=h.id,away_team_id=a.id,home_goals=hg,away_goals=ag)
    db.add(f)
    db.flush()
    if status=='NS':
        # Generate fake odds for demonstration only.
        db.add(OddsSnapshot(fixture_provider_id=f.provider_id,event_provider_id=f'demo-{i}',bookmaker='demo-book',market='h2h',selection=h.name,odds=round(random.uniform(1.6,3.2),2)))
        db.add(OddsSnapshot(fixture_provider_id=f.provider_id,event_provider_id=f'demo-{i}',bookmaker='demo-book',market='h2h',selection='DRAW',odds=round(random.uniform(3.1,4.2),2)))
        db.add(OddsSnapshot(fixture_provider_id=f.provider_id,event_provider_id=f'demo-{i}',bookmaker='demo-book',market='h2h',selection=a.name,odds=round(random.uniform(1.8,4.2),2)))
db.add(BankrollEvent(event_type='INITIAL',amount=1000,balance_after=1000,note='Demo bankroll'))
db.commit(); db.close()
print('Inserted demo fixtures and odds.')
