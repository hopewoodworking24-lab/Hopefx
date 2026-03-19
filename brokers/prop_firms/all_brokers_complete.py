import asyncio
import aiohttp

class Broker:
    async def fetch_data(self):
        raise NotImplementedError

class FTMO(Broker):
    async def fetch_data(self):
        # Implement FTMO data fetching with error handling
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://ftmo.com/data') as response:
                    response.raise_for_status()
                    return await response.json()
        except Exception as e:
            print(f'Error fetching FTMO data: {e}')

class The5ers(Broker):
    async def fetch_data(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://the5ers.com/api') as response:
                    response.raise_for_status()
                    return await response.json()
        except Exception as e:
            print(f'Error fetching The5ers data: {e}')

class MyForexFunds(Broker):
    async def fetch_data(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://myforexfunds.com/api') as response:
                    response.raise_for_status()
                    return await response.json()
        except Exception as e:
            print(f'Error fetching MyForexFunds data: {e}')

class TopStep(Broker):
    async def fetch_data(self):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get('https://topstep.com/api') as response:
                    response.raise_for_status()
                    return await response.json()
        except Exception as e:
            print(f'Error fetching TopStep data: {e}')

async def main():
    brokers = [FTMO(), The5ers(), MyForexFunds(), TopStep()]
    tasks = [broker.fetch_data() for broker in brokers]
    results = await asyncio.gather(*tasks)
    print(results)

if __name__ == '__main__':
    asyncio.run(main())