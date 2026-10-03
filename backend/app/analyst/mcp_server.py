"""MCP server exposing read-only scene statistics to an LLM client (FR-41).

Run over stdio:  python -m app.analyst.mcp_server
Every tool takes a job id and returns derived statistics only (see tools.guard_stats_only).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from app.analyst import tools
from app.core.config import get_settings

server = MCPServer(
    name="aakashdrishti-analyst",
    instructions=(
        "Read-only statistics about a reconstructed terrain scene. Cite only numbers returned by these tools, "
        "and state the vertical-error uncertainty explicitly."
    ),
)


def _dir(job_id: str):
    return get_settings().output_dir_path / job_id


@server.tool()
def get_scene_summary(job_id: str) -> dict:
    """Bounds, CRS, GSD, height range, mean height, class area breakdown."""
    return tools.get_scene_summary(_dir(job_id))


@server.tool()
def get_height_profile(job_id: str, x0: float, y0: float, x1: float, y1: float) -> dict:
    """Elevation samples along a line between two pixel positions."""
    return tools.get_height_profile(_dir(job_id), [[x0, y0], [x1, y1]])


@server.tool()
def get_flood_result(job_id: str, water_level: float | None = None) -> dict:
    """Inundated area, affected buildings and worst-hit sub-areas for a water level above the reference."""
    return tools.get_flood_result(_dir(job_id), water_level)


@server.tool()
def get_landing_zones(job_id: str) -> dict:
    """Ranked candidate landing zones with scores (candidate sites for operator confirmation)."""
    return tools.get_landing_zones(_dir(job_id))


@server.tool()
def get_slope_stats(job_id: str) -> dict:
    """Slope distribution and the area above hazard thresholds."""
    return tools.get_slope_stats(_dir(job_id))


@server.tool()
def get_validation_metrics(job_id: str) -> dict:
    """RMSE, MAE, r and per-class errors when reference data was supplied."""
    return tools.get_validation_metrics(_dir(job_id))


if __name__ == "__main__":
    server.run("stdio")
