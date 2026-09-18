import { afterEach, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";

import { usePipelineJob } from "@/hooks/use-pipeline-job";
import { proxyFetcher } from "@/lib/proxy-fetcher";

vi.mock("@/lib/proxy-fetcher", () => ({ proxyFetcher: vi.fn() }));
afterEach(cleanup);

it("fetches pipeline jobs only after a bid is selected", async () => {
  vi.mocked(proxyFetcher).mockResolvedValue({ jobs: [] });
  const cache = new Map();
  const { rerender } = renderHook(({ code }) => usePipelineJob(code), {
    initialProps: { code: "" },
    wrapper: ({ children }) => <SWRConfig value={{ provider: () => cache }}>{children}</SWRConfig>,
  });
  expect(proxyFetcher).not.toHaveBeenCalled();

  rerender({ code: "CBC-260006" });
  await waitFor(() => expect(proxyFetcher).toHaveBeenCalledExactlyOnceWith(
    "/api/proxy/jobs?project=CBC-260006&pipeline_active=true",
  ));

  rerender({ code: "" });
  expect(proxyFetcher).toHaveBeenCalledTimes(1);
});
