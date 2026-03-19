"""
Social Trading Performance Metrics
- Win rate calculations
- Return on investment tracking
- Risk-adjusted performance
"""

from typing import List, Dict
import numpy as np

class SocialPerformanceMetrics:
    """Calculate social trading performance"""
    
    @staticmethod
    def calculate_win_rate(trades: List[Dict]) -> float:
        """Calculate win rate"""
        if not trades:
            return 0.0
        winning = len([t for t in trades if t.get('pnl', 0) > 0])
        return winning / len(trades)
    
    @staticmethod
    def calculate_sharpe_ratio(returns: List[float], risk_free_rate: float = 0.02) -> float:
        """Calculate Sharpe ratio"""
        if not returns or len(returns) < 2:
            return 0.0
        
        returns = np.array(returns)
        excess_returns = returns - (risk_free_rate / 252)
        sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
        return float(sharpe)
    
    @staticmethod
    def calculate_max_drawdown(equity_curve: List[float]) -> float:
        """Calculate maximum drawdown"""
        if not equity_curve:
            return 0.0
        
        equity = np.array(equity_curve)
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max
        return float(np.min(drawdown))
    
    @staticmethod
    def calculate_profit_factor(trades: List[Dict]) -> float:
        """Calculate profit factor"""
        winning_sum = sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) > 0)
        losing_sum = abs(sum(t.get('pnl', 0) for t in trades if t.get('pnl', 0) < 0))
        
        if losing_sum == 0:
            return 0.0
        return winning_sum / losing_sum
    
    @staticmethod
    def calculate_roi(initial_balance: float, final_balance: float) -> float:
        """Calculate return on investment"""
        if initial_balance == 0:
            return 0.0
        return ((final_balance - initial_balance) / initial_balance) * 100