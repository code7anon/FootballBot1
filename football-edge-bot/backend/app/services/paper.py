from __future__ import annotations
from datetime import datetime, date
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from ..config import get_settings
from ..models import Bet, BankrollEvent, SystemState, Fixture, Team

settings = get_settings()


class PaperTrader:
    def __init__(self, db: Session):
        self.db = db

    def balance(self) -> float:
        latest = self.db.scalar(select(BankrollEvent).order_by(BankrollEvent.id.desc()).limit(1))
        return float(latest.balance_after) if latest else settings.initial_bankroll

    def ensure_bankroll(self):
        if not self.db.scalar(select(BankrollEvent).limit(1)):
            self.db.add(BankrollEvent(event_type="INITIAL", amount=settings.initial_bankroll,
                                      balance_after=settings.initial_bankroll, note="Initial paper bankroll"))
            self.db.commit()

    def can_bet(self, stake: float) -> bool:
        today = date.today()
        count = self.db.scalar(select(func.count(Bet.id)).where(func.date(Bet.created_at) == today)) or 0
        open_exposure = self.db.scalar(select(func.coalesce(func.sum(Bet.stake), 0)).where(Bet.status == "OPEN")) or 0
        return count < settings.max_daily_bets and open_exposure + stake <= self.balance() * settings.max_open_exposure_pct

    def place(self, fixture: Fixture, market: str, selection: str, odds: float, probability: float, edge: float, stake: float, metadata: dict | None = None) -> Bet | None:
        self.ensure_bankroll()
        if not self.can_bet(stake):
            return None
        duplicate = self.db.scalar(select(Bet).where(
            Bet.fixture_id == fixture.id,
            Bet.market == market,
            Bet.selection == selection,
            Bet.status == "OPEN",
        ).limit(1))
        if duplicate:
            return None
        bet = Bet(
            fixture_id=fixture.id,
            mode="PAPER",
            status="OPEN",
            market=market,
            selection=selection,
            odds=odds,
            model_probability=probability,
            edge=edge,
            stake=stake,
            potential_payout=stake * odds,
            metadata_json=metadata or {},
        )
        self.db.add(bet)
        self.db.commit()
        return bet

    def settle_open(self) -> int:
        open_bets = self.db.scalars(select(Bet).where(Bet.status == "OPEN")).all()
        settled = 0
        balance = self.balance()
        for bet in open_bets:
            if not bet.fixture_id:
                continue
            fixture = self.db.get(Fixture, bet.fixture_id)
            if not fixture or fixture.status not in {"FT", "AET", "PEN"} or fixture.home_goals is None:
                continue
            if bet.market == "h2h":
                home = self.db.get(Team, fixture.home_team_id)
                away = self.db.get(Team, fixture.away_team_id)
                winner = home.name if fixture.home_goals > fixture.away_goals else away.name if fixture.away_goals > fixture.home_goals else "DRAW"
                won = bet.selection == winner or (bet.selection.upper() == "DRAW" and winner == "DRAW")
            elif bet.market == "totals":
                total = fixture.home_goals + fixture.away_goals
                if "OVER" in bet.selection.upper():
                    won = total > 2.5
                elif "UNDER" in bet.selection.upper():
                    won = total < 2.5
                else:
                    won = False
            else:
                continue
            pnl = bet.stake * (bet.odds - 1) if won else -bet.stake
            balance += pnl
            bet.pnl = pnl
            bet.status = "WON" if won else "LOST"
            bet.settled_at = datetime.utcnow()
            self.db.add(BankrollEvent(event_type="BET_SETTLEMENT", amount=pnl, balance_after=balance, reference_id=bet.id, note=bet.status))
            settled += 1
        if settled:
            self.db.commit()
        return settled
