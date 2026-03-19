class CopyTradingEngine:
    def __init__(self):
        self.traders = {}  # Dictionary to hold traders information
        self.followers = {}  # Dictionary to hold followers information
        self.signals = []  # List to store signals broadcasted
        self.performance = {}  # Dictionary to track performance of traders

    def register_trader(self, trader_id, trader_info):
        """Registers a new trader with their information."""
        if trader_id not in self.traders:
            self.traders[trader_id] = trader_info
            self.performance[trader_id] = []  # Initialize performance tracking
            print(f"Trader {trader_id} registered successfully.")
        else:
            print(f"Trader {trader_id} is already registered.")

    def subscribe_follower(self, follower_id, trader_id):
        """Allows a follower to subscribe to a trader for signals."""
        if trader_id in self.traders:
            if trader_id not in self.followers:
                self.followers[trader_id] = []
            self.followers[trader_id].append(follower_id)
            print(f"Follower {follower_id} subscribed to trader {trader_id}.")
        else:
            print(f"Trader {trader_id} not found.")

    def broadcast_signal(self, trader_id, signal):
        """Broadcasts a trading signal from a trader to all their followers."""
        if trader_id in self.followers:
            self.signals.append((trader_id, signal))
            for follower in self.followers[trader_id]:
                self.notify_follower(follower, signal)
            self.track_performance(trader_id, signal)
        else:
            print(f"No followers for trader {trader_id}.")

    def notify_follower(self, follower_id, signal):
        """Notifies a follower about a new signal."""
        print(f"Notifying follower {follower_id}: New signal from trader: {signal}")

    def track_performance(self, trader_id, signal):
        """Tracks the performance of the trader based on the signal."""
        # Here you can add logic to calculate performance
        self.performance[trader_id].append(signal)  # Placeholder for performance data collection
        print(f"Tracking performance for trader {trader_id}.")

    def get_performance(self, trader_id):
        """Returns performance data for a trader."""
        return self.performance.get(trader_id, [])

# Example usage:
# engine = CopyTradingEngine()
# engine.register_trader('trader1', {'name': 'John Doe', 'strategy': 'trend following'})
# engine.subscribe_follower('follower1', 'trader1')
# engine.broadcast_signal('trader1', 'Buy signal for XYZ')