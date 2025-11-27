+-------------------------------+
|        Outer Layer            |
|  adapters + infrastructure    |
|  - routers/controllers        |
|  - presenters                 |
|  - repositories               |
|  - external API clients       |
|  - DI/dependencies            |
|  - caching / DB plumbing      |
|  - logging / metrics / APM    |
|  - middleware / MCP, etc.     |
+-------------------------------+
               ↓
+-------------------------------+
|         Application           |
|  - use cases                  |
|  - DTOs                       |
|  - UoW                        |
|  - ports (gateways)           |
+-------------------------------+
               ↓
+-------------------------------+
|           Domain              |
|  - entities / value objects   |
|  - domain services            |
|  - domain exceptions          |
|  - domain interfaces          |
+-------------------------------+
