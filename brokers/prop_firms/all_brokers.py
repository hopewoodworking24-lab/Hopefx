from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class PropFirmMetrics:
    drawdown: float
    profit_factor: float
    total_trades: int
    winning_trades: int

@dataclass
class PropFirmTrade:
    trade_id: str
    entry_price: float
    exit_price: float
    volume: float
    profit: float

class BasePropFirmBroker(ABC):
    @abstractmethod
    def get_metrics(self) -> PropFirmMetrics:
        pass

    @abstractmethod
    def execute_trade(self, trade: PropFirmTrade) -> None:
        pass

class FTMOBroker(BasePropFirmBroker):
    def get_metrics(self) -> PropFirmMetrics:
        # Implementation for FTMO metrics
        return PropFirmMetrics(drawdown=2.5, profit_factor=1.5, total_trades=100, winning_trades=60)

    def execute_trade(self, trade: PropFirmTrade) -> None:
        # Execute FTMO trade
        pass

class The5ersBroker(BasePropFirmBroker):
    def get_metrics(self) -> PropFirmMetrics:
        return PropFirmMetrics(drawdown=3.0, profit_factor=1.8, total_trades=80, winning_trades=50)

    def execute_trade(self, trade: PropFirmTrade) -> None:
        pass

class MyForexFundsBroker(BasePropFirmBroker):
    def get_metrics(self) -> PropFirmMetrics:
        return PropFirmMetrics(drawdown=1.5, profit_factor=2.0, total_trades=120, winning_trades=70)

    def execute_trade(self, trade: PropFirmTrade) -> None:
        pass

class TopStepBroker(BasePropFirmBroker):
    def get_metrics(self) -> PropFirmMetrics:
        return PropFirmMetrics(drawdown=4.0, profit_factor=1.2, total_trades=90, winning_trades=45)

    def execute_trade(self, trade: PropFirmTrade) -> None:
        pass

class PropFirmFactory:
    @staticmethod
    def create_broker(broker_name: str) -> BasePropFirmBroker:
        brokers = {
            'FTMO': FTMOBroker(),
            'The5ers': The5ersBroker(),
            'MyForexFunds': MyForexFundsBroker(),
            'TopStep': TopStepBroker(),
        }
        return brokers.get(broker_name)

# Example usage
if __name__ == '__main__':
    broker = PropFirmFactory.create_broker('FTMO')
    metrics = broker.get_metrics()
    print(metrics)
    trade = PropFirmTrade(trade_id='001', entry_price=1.1234, exit_price=1.1250, volume=1.0, profit=15.0)
    broker.execute_trade(trade)