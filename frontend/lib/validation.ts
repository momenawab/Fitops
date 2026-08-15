import { z } from "zod";

// Configuration example only; product schemas belong to their owning stories.
export const exampleSchema = z.object({
  value: z.string(),
});

export type ExampleValues = z.infer<typeof exampleSchema>;
