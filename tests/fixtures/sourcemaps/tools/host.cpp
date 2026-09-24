// Minimal Hermes host: runs a bytecode (or JS) file under a given source URL,
// exposes print(), drains microtasks, and prints the stack of any uncaught error.
#include <hermes/hermes.h>
#include <jsi/jsi.h>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>

using namespace facebook;

int main(int argc, char **argv) {
  if (argc < 3) { std::cerr << "usage: host <file> <sourceURL>\n"; return 2; }
  std::ifstream in(argv[1], std::ios::binary);
  std::string data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
  auto config = ::hermes::vm::RuntimeConfig::Builder().withMicrotaskQueue(true).build();
  auto rt = facebook::hermes::makeHermesRuntime(config);
  jsi::Runtime &r = *rt;
  r.global().setProperty(r, "print", jsi::Function::createFromHostFunction(
      r, jsi::PropNameID::forAscii(r, "print"), 1,
      [](jsi::Runtime &rt, const jsi::Value &, const jsi::Value *args, size_t n) {
        for (size_t i = 0; i < n; i++) std::cout << (i ? " " : "") << args[i].toString(rt).utf8(rt);
        std::cout << "\n";
        return jsi::Value::undefined();
      }));
  int rc = 0;
  // Extra scripts (argv[3..]) run after the bundle, even if it threw: they
  // drive app code through the bundle's own require (global.__r).
  auto runExtras = [&]() {
    for (int i = 3; i < argc; i++) {
      std::ifstream ex(argv[i], std::ios::binary);
      std::string src((std::istreambuf_iterator<char>(ex)), std::istreambuf_iterator<char>());
      try {
        r.evaluateJavaScript(std::make_shared<jsi::StringBuffer>(src), argv[i]);
        r.drainMicrotasks();
      } catch (jsi::JSError &e) {
        std::cout << "@@UNCAUGHT\n" << e.getStack() << "\n@@END\n";
      }
    }
  };
  try {
    r.evaluateJavaScript(std::make_shared<jsi::StringBuffer>(data), argv[2]);
    r.drainMicrotasks();
  } catch (jsi::JSError &e) {
    std::cout << "@@UNCAUGHT\n" << e.getStack() << "\n@@END\n";
    rc = 1;
    try { r.drainMicrotasks(); } catch (jsi::JSError &e2) {
      std::cout << "@@UNCAUGHT\n" << e2.getStack() << "\n@@END\n";
    }
  } catch (std::exception &e) {
    std::cout << "@@EXCEPTION " << e.what() << "\n";
    rc = 3;
  }
  runExtras();
  return rc;
}
