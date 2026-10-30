"""Wrap the typed tool functions as LangChain tools for the agent."""

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool, ToolException
from pydantic import BaseModel

from spotwise.tools import price_tools as t
from spotwise.tools.periods import PeriodError

# (function, input model, description the LLM reads to choose a tool)
TOOL_SPECS: list[tuple[Callable[..., BaseModel], type[BaseModel], str]] = [
    (
        t.resolve_period,
        t.PeriodInput,
        "Turn a time phrase into an exact Helsinki start/end. ALWAYS call this first "
        "for any date or time phrase; never compute dates yourself.",
    ),
    (
        t.get_current_price,
        t.NoInput,
        "Price of the slot running right now, incl. and excl. VAT.",
    ),
    (
        t.get_prices,
        t.PricesInput,
        "List of prices for a range (hourly by default, max 100 points). Prefer "
        "get_price_stats or the window tools for summaries.",
    ),
    (
        t.find_cheapest_window,
        t.WindowInput,
        "Cheapest continuous block of a given length (e.g. 180 min to charge an EV) "
        "inside a range.",
    ),
    (
        t.find_most_expensive_window,
        t.WindowInput,
        "Most expensive continuous block of a given length inside a range.",
    ),
    (
        t.get_price_stats,
        t.RangeInput,
        "Min and max (with times), mean, median and negative-price slots for a range. "
        "Use for 'cheapest/most expensive hour', averages and negative prices.",
    ),
    (
        t.compare_periods,
        t.CompareInput,
        "Compare the mean price of period b with period a (difference and percent).",
    ),
    (
        t.estimate_cost,
        t.CostInput,
        "Cost in euros of using N kWh spread evenly over a range, excl. and incl. VAT.",
    ),
    (
        t.check_data_availability,
        t.AvailabilityInput,
        "Whether a day's prices are published yet (default: tomorrow).",
    ),
]


def build_tools(ctx: t.ToolContext) -> list[BaseTool]:
    """LangChain tools bound to one ToolContext. Outputs are JSON strings."""
    return [_wrap(ctx, fn, schema, description) for fn, schema, description in TOOL_SPECS]


def _wrap(
    ctx: t.ToolContext,
    fn: Callable[..., BaseModel],
    schema: type[BaseModel],
    description: str,
) -> BaseTool:
    def run(**kwargs: Any) -> str:
        try:
            return fn(ctx, schema(**kwargs)).model_dump_json()
        except (PeriodError, ValueError) as exc:
            # Sent back to the LLM as the tool result so it can correct itself
            raise ToolException(str(exc)) from None

    return StructuredTool.from_function(
        func=run,
        name=fn.__name__,
        description=description,
        args_schema=schema,
        handle_tool_error=True,
        handle_validation_error=True,
    )
