# FundsPortfolio

[![CI/CD](https://github.com/LowFatMatt/FundsPortfolio/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/LowFatMatt/FundsPortfolio/actions)

## What this Software does

This Software is a portfolio manager for funds. That is, it can thake anything that has an ISIN and create an initial Database of the list of funds. The user is then asked a few questions about the financial situation he is in and how risk averse oder riskinclined he is when it comes to investments. The user can then choose his personal portfolio out of the Database and the Software will calculate the best possible portfolio for him by filtering the Database based on the users answers. Portfolios get a unique ID that is sorted by the date of creation but otherwise not human readable.

## How it works

The Software works by using the ISIN of the fund to get the fund's KIID. The KIID is then used to get the fund's performance data. The performance data is then used to calculate the expected return and the risk of the fund. The expected return and the risk are then used to calculate the Sharpe Ratio of the fund. The Sharpe Ratio is then used to rank the funds. The funds are then sorted by their Sharpe Ratio and the top 100 funds are selected. The selected funds are then used to calculate the best possible portfolio for the user based on the users answers.

## Architecture

The Logic of the Software is built using Python and the following libraries:
- pandas
- numpy
- matplotlib
- yfinance
- 

The Frontend of the Software is built using HTML, CSS and JavaScript.

## How to use it

### Admin

The Admin can add new Funds to the Database. He can also edit existing Funds.
a Database entry has the following attributes:
- ISIN
- Name
- URL to the Fund (e.g. on the website of the Fund)
- URL to the Fund's KIID

There is no GUI for the Admin. 
The initial Database is just a JSON file.
There is another JSON file that defines the questions the user is asked.

### User

The User can create a Portfolio out of the Database. He can also edit existing Portfolios.
a Portfolio entry has the following attributes:
- ID
- Name
- Date of creation
- ISINs of the Funds in the Portfolio
- Answers of the user to the questions

The entry URL can take the poitfolio ID as an optional parameter. If it is not provided, the user is asked to etner it malually or cninue wihtout an existing ID in which case a new Portfolio is created automatically. If it is provided, the user is asked shown the Portfolio with the given ID which he can then edit.

### Machine Access

The Software can also be used by machines. It will not respond to any GUI requests but will instead return the data as JSON. In case it is called with a portfolio ID, it will return the portfolio with the given ID. 
In case it is called without a portfolio ID, it will create a new Portfolio and return its ID and empty sting answers and exit. The machine can then fill in the answers and call the Software again with the portfolio ID. 
