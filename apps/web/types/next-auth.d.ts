import type { DefaultSession } from "next-auth";

declare module "next-auth" {
  interface Session {
    user: DefaultSession["user"] & {
      id: string;
      initials: string;
      role: string;
    };
  }

  interface User {
    initials?: string;
    role?: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    initials?: string;
    role?: string;
  }
}
