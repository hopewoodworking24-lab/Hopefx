# Feature Engineering for ML Models

This module provides advanced feature engineering techniques commonly used in machine learning, particularly for time series analysis and stocks.

## 1. Price Features
These features are based on the price of the asset and include:
- **Moving Averages**: Useful for smoothing price data. Example usage:
  ```python
  df['MA_10'] = df['Close'].rolling(window=10).mean()
  ```
- **Returns**: Calculate daily returns.
  ```python
  df['Returns'] = df['Close'].pct_change()
  ```

## 2. Volatility Features
Volatility can indicate the risk associated with a particular investment.
- **Standard Deviation**: It can be measured over a rolling window.
  ```python
  df['Volatility'] = df['Returns'].rolling(window=10).std()
  ```

## 3. Momentum Features
These features help gauge the strength of a trend.
- **Momentum**: The difference between the current price and the price n days ago.
  ```python
  df['Momentum'] = df['Close'] - df['Close'].shift(10)
  ```

## 4. Trend Features
Capture the overall direction of the asset price.
- **Trend**: Using linear regression to estimate trend.
  ```python
  from sklearn.linear_model import LinearRegression
  model = LinearRegression()
  model.fit(df.index.values.reshape(-1,1), df['Close'].values)
  df['Trend'] = model.predict(df.index.values.reshape(-1,1))
  ```

## 5. Volume Features
Volume can indicate potential buy/sell signals.
- **Volume Moving Average**: Typical volume block over a time period.
  ```python
  df['Volume_MA'] = df['Volume'].rolling(window=10).mean()
  ```

## 6. Pattern Recognition Features
Identify price patterns that can be indicative of future movements.
- **Head and Shoulders**: Custom function to detect pattern.
  ```python
  def head_and_shoulders(df):
      # Implement logic to identify head and shoulders pattern
      pass
  ```

## Example Usage
```python
import pandas as pd
from your_module import feature_engineering

df = pd.read_csv('path_to_your_data.csv')
feature_engineering.apply_features(df)
```