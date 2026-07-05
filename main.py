from agent import TradingAgent

def main():
    print("Trading Assistant Ready. Type 'exit' to quit, 'reset' to clear conversation.\n")
    agent = TradingAgent()

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == "exit":
            break
        if user_input.lower() == "reset":
            agent.reset()
            continue
        if not user_input:
            continue

        answer = agent.ask(user_input)
        print(f"\nAgent: {answer}\n")

if __name__ == "__main__":
    main()