import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Home from "@/app/page";
import { cn } from "@/lib/utils";

describe("Smoke tests", () => {
  it("renders the Home page component in jsdom", () => {
    render(<Home />);

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.textContent).toBe("FitOps");
    expect(
      screen.getByText("The frontend foundation is running.")
    ).not.toBeNull();
  });

  it("merges Tailwind classes and resolves conflicts using cn()", () => {
    expect(cn("px-2 py-1", "px-4")).toBe("py-1 px-4");
    expect(cn("font-bold", false && "italic", true && "text-center")).toBe(
      "font-bold text-center"
    );
  });
});
