import { expect, it, vi } from "vitest";
import { req } from "../../api";
import { getMcpConfig, saveMcpConfig, testMcpServer } from "./api";
vi.mock("../../api",()=>({req:vi.fn()}));
it("uses the existing authenticated base-path request wrapper",async()=>{
 await getMcpConfig();
 await saveMcpConfig({revision:2,servers:[]});
 await testMcpServer("local");
 expect(req).toHaveBeenNthCalledWith(1,"/api/settings/mcp");
 expect(req).toHaveBeenNthCalledWith(2,"/api/settings/mcp",expect.objectContaining({method:"PUT",body:'{"revision":2,"servers":[]}'}));
 expect(req).toHaveBeenNthCalledWith(3,"/api/settings/mcp/local/test",{method:"POST"});
});

