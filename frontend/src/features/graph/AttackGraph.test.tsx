import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Graph, GraphNode } from "../../types";
import { AttackGraph } from "./AttackGraph";

function node(key: string, type: string, severity = "info", tags: string[] = []): GraphNode {
  return { id: key, key, type, severity, tags, title: `${key} title`, status: "open", is_rce: false, risk_score: 30 };
}

function sampleGraph(): Graph {
  return {
    nodes: [node("target:example", "target"), node("info:1", "info"), node("vuln:1", "vuln", "high"), node("goal:shell", "goal", "critical")],
    edges: [
      { id: "edge-1", from: "target:example", to: "info:1", relation: "CONTAINS", weight: 1, on_rce_path: false },
      { id: "edge-2", from: "info:1", to: "vuln:1", relation: "LEADS_TO", weight: 1, on_rce_path: true },
      { id: "edge-3", from: "vuln:1", to: "goal:shell", relation: "LEADS_TO", weight: 1, on_rce_path: true },
    ],
    findings: [],
    rce_path: { path: ["target:example", "info:1", "vuln:1", "goal:shell"], likelihood: 0.8 },
    stats: { nodes: 4, edges: 3, findings: 1, critical: 1, has_shell: true },
  };
}

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ width: 900, height: 560, x: 0, y: 0, top: 0, left: 0, right: 900, bottom: 560, toJSON: () => ({}) });
  vi.stubGlobal("ResizeObserver", class {
    constructor(private callback: ResizeObserverCallback) {}
    observe() { this.callback([], this as unknown as ResizeObserver); }
    disconnect() {}
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("hides information nodes and their edges without connecting across gaps in the RCE path", () => {
  const graph = sampleGraph();
  const { container } = render(<AttackGraph graph={graph} onSelect={() => {}} />);
  expect(container.querySelectorAll("[data-node]")).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  fireEvent.click(screen.getByRole("button", { name: "隐藏信息节点" }));
  expect(container.querySelector('[data-node="info:1"]')).toBeNull();
  expect(container.querySelectorAll("svg line")).toHaveLength(1);
  const path = container.querySelector(".graph-rce-path");
  expect(path?.getAttribute("points")?.split(" ")).toHaveLength(2);
  expect(screen.getByText("显示 3 / 4 个节点")).toBeInTheDocument();
  expect(graph.nodes).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "全部展示" }));
  expect(container.querySelectorAll("[data-node]")).toHaveLength(4);
  expect(container.querySelectorAll("svg line")).toHaveLength(3);
});

it("combines type and severity filters and supports an empty selection", () => {
  const { container } = render(<AttackGraph graph={sampleGraph()} onSelect={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  const types = within(screen.getByRole("group", { name: "节点类型" }));
  const severities = within(screen.getByRole("group", { name: "风险等级" }));
  fireEvent.click(types.getByRole("checkbox", { name: /^漏洞/ }));
  fireEvent.click(severities.getByRole("checkbox", { name: /^信息/ }));
  expect(container.querySelectorAll("[data-node]")).toHaveLength(1);
  expect(container.querySelector('[data-node="goal:shell"]')).toBeInTheDocument();
  fireEvent.click(severities.getByRole("checkbox", { name: /^严重/ }));
  expect(container.querySelectorAll("[data-node]")).toHaveLength(0);
  expect(container.querySelectorAll("svg line, .graph-rce-path")).toHaveLength(0);
  expect(screen.getByText("没有符合筛选条件的节点")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "全部展示" }));
  expect(container.querySelectorAll("[data-node]")).toHaveLength(4);
});

it("keeps filters for new snapshots and uses the displayed classification for placeholders", () => {
  const graph = sampleGraph();
  const { container, rerender } = render(<AttackGraph graph={graph} onSelect={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  fireEvent.click(screen.getByRole("button", { name: "隐藏信息节点" }));
  const next = { ...graph, nodes: [...graph.nodes, node("info:2", "info"), node("vuln:placeholder", "vuln", "critical", ["placeholder"]), node("service:1", "service")] };
  rerender(<AttackGraph graph={next} onSelect={() => {}} />);
  expect(container.querySelector('[data-node="info:2"]')).toBeNull();
  expect(container.querySelector('[data-node="service:1"]')).toBeInTheDocument();
  const types = within(screen.getByRole("group", { name: "节点类型" }));
  fireEvent.click(types.getByRole("checkbox", { name: /^漏洞/ }));
  expect(container.querySelector('[data-node="vuln:placeholder"]')).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole("group", { name: "风险等级" })).getByRole("checkbox", { name: /^中/ }));
  expect(container.querySelector('[data-node="vuln:placeholder"]')).toBeNull();
  const changed = { ...next, nodes: next.nodes.map((item) => item.key === "service:1" ? { ...item, type: "info" } : item) };
  rerender(<AttackGraph graph={changed} onSelect={() => {}} />);
  expect(container.querySelector('[data-node="service:1"]')).toBeNull();
});

it("clears hidden selections and preserves filters when entering and exiting fullscreen", () => {
  const onClear = vi.fn();
  const { container } = render(<AttackGraph graph={sampleGraph()} selectedKey="info:1" onSelect={() => {}} onClear={onClear} />);
  expect(container.querySelector(".graph-node-popover")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  fireEvent.click(screen.getByRole("button", { name: "隐藏信息节点" }));
  expect(onClear).toHaveBeenCalledOnce();
  expect(container.querySelector(".graph-node-popover")).toBeNull();
  Object.defineProperty(document, "fullscreenElement", { configurable: true, value: container.querySelector(".graph-wrap") });
  act(() => { document.dispatchEvent(new Event("fullscreenchange")); });
  expect(screen.getByRole("button", { name: "退出全屏" })).toBeInTheDocument();
  expect(container.querySelector('[data-node="info:1"]')).toBeNull();
  Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
  act(() => { document.dispatchEvent(new Event("fullscreenchange")); });
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  expect(container.querySelector('[data-node="info:1"]')).toBeNull();
});

it("updates visible snapshot metadata without resetting the viewport or active filters", () => {
  const graph = sampleGraph();
  const { container, rerender } = render(<AttackGraph graph={graph} onSelect={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  fireEvent.click(screen.getByRole("button", { name: "隐藏信息节点" }));
  const transform = container.querySelector("svg > g")?.getAttribute("transform");
  const next = { ...graph, nodes: graph.nodes.map((item) => item.key === "vuln:1" ? { ...item, title: "Updated finding", severity: "medium", risk_score: 50 } : item) };
  rerender(<AttackGraph graph={next} onSelect={() => {}} />);
  const finding = container.querySelector('[data-node="vuln:1"]');
  expect(finding).toHaveTextContent("Updated finding");
  expect(finding?.querySelector("circle")?.getAttribute("stroke")).toBe("#d4a017");
  expect(finding?.querySelector("circle")?.getAttribute("r")).toBe("17");
  expect(container.querySelector("svg > g")?.getAttribute("transform")).toBe(transform);
  expect(container.querySelector('[data-node="info:1"]')).toBeNull();
});

it("clears omitted snapshot details so rendered placeholder classification matches the filters", () => {
  const original = sampleGraph();
  const graph = { ...original, nodes: original.nodes.map((item) => item.key === "vuln:1" ? { ...item, title: item.key, detail: "Verified detail" } : item) };
  const { container, rerender } = render(<AttackGraph graph={graph} onSelect={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "节点筛选" }));
  fireEvent.click(screen.getByRole("button", { name: "隐藏信息节点" }));
  const next = { ...graph, nodes: graph.nodes.map((item) => {
    const { detail, ...withoutDetail } = item;
    return withoutDetail;
  }) };
  rerender(<AttackGraph graph={next} onSelect={() => {}} />);
  const finding = container.querySelector('[data-node="vuln:1"] circle');
  expect(finding?.getAttribute("fill")).toBe("#f08c2a");
  expect(finding?.getAttribute("stroke")).toBe("#d4a017");
});
