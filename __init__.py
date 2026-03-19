"""
HOPEFX AI Trading Framework
Advanced AI-powered trading framework with machine learning, real-time analysis,
multi-broker integration, and intelligent trade execution.
"""

__version__ = '1.0.0'
__author__ = 'HOPEFX Team'
__license__ = 'MIT'

# Core modules
from social.copy_trading import CopyTradingEngine, TraderProfile, FollowerConfig
from social.leaderboards import PerformanceLeaderboard
from social.profiles import TraderProfile as SocialTraderProfile
from social.performance import SocialPerformanceMetrics

# ML modules
from ml.models.base import BaseMLModel
from ml.models.lstm import LSTMPricePredictor
from ml.models.random_forest import RandomForestTradingClassifier
from ml.models.ensemble import EnsembleModel
from ml.features.feature_engineering import TechnicalFeatureEngineer

# Data modules
from data.streaming import DataStreamingService, MarketDataStreamEvent
from data.depth_of_market import DepthOfMarketManager
from data.time_and_sales import TimeAndSalesTape

# Charting modules
from charting.indicators import TechnicalIndicators
from charting.chart_engine import ChartEngine

# Analysis modules
from analysis.market_analysis import MarketRegimeDetector, SessionAnalyzer
from analysis.order_flow import OrderFlowAnalyzer, VolumeProfile
from analysis.advanced_order_flow import AggressionMetrics, DeltaDivergence
from analysis.institutional_flow import InstitutionalFlowDetector
from analysis.market_scanner import MarketScanner

# Notifications
from notifications.alert_engine import AlertEngine, Alert
from notifications.manager import NotificationManager

# Payments
from payments.payment_gateway import PaymentGateway, Payment

# Brokers
from brokers.factory import BrokerFactory
from brokers.advanced_orders import OCOOrder, TrailingStopOrder, BracketOrder

# Teams & Security
from teams.team_manager import TeamManager, Team
from security.security_manager import SecurityManager

# Compliance
from compliance.compliance_manager import ComplianceManager

# Import main components
from config import ConfigManager, initialize_config
from cache import MarketDataCache, Timeframe
from database import Base

# Import trading components
from strategies import (
    BaseStrategy, Signal, SignalType, StrategyStatus,
    StrategyManager, MovingAverageCrossover
)
from risk import RiskManager, RiskConfig, PositionSize, PositionSizeMethod
from brokers import (
    BrokerConnector, Order, Position, AccountInfo,
    OrderType, OrderSide, OrderStatus, PaperTradingBroker
)
from notifications import NotificationManager, NotificationLevel, NotificationChannel

__all__ = [
   
     'CopyTradingEngine',
    'PerformanceLeaderboard
    
     # Version info
    '__version__',
    '__author__',
    '__license__',

    # Configuration
    'ConfigManager',
    'initialize_config',

    # Cache
    'MarketDataCache',
    'Timeframe',

    # Database
    'Base',

    # Strategies
    'BaseStrategy',
    'Signal',
    'SignalType',
    'StrategyStatus',
    'StrategyManager',
    'MovingAverageCrossover',

    # Risk Management
    'RiskManager',
    'RiskConfig',
    'PositionSize',
    'PositionSizeMethod',

    # Brokers
    'BrokerConnector',
    'Order',
    'Position',
    'AccountInfo',
    'OrderType',
    'OrderSide',
    'OrderStatus',
    'PaperTradingBroker',

    # Notifications
    'NotificationManager',
    'NotificationLevel',
    'NotificationChannel',
]
