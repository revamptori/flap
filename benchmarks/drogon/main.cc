#include <drogon/drogon.h>
using namespace drogon;
int main() {
    app().registerHandler("/", [](const HttpRequestPtr& req, std::function<void(const HttpResponsePtr&)>&& cb){ auto resp=HttpResponse::newHttpResponse(); resp->setBody("Hello, Drogon!"); resp->setStatusCode(k200OK); cb(resp); }, {Get});
    app().registerHandler("/hello/{name}", [](const HttpRequestPtr& req, std::function<void(const HttpResponsePtr&)>&& cb, std::string name){ auto resp=HttpResponse::newHttpResponse(); resp->setBody("Hello, "+name+"!"); cb(resp); }, {Get});
    app().registerHandler("/user/{id}", [](const HttpRequestPtr& req, std::function<void(const HttpResponsePtr&)>&& cb, std::string id){ Json::Value j; j["id"]=id; j["name"]="Ada"; auto resp=HttpResponse::newHttpJsonResponse(j); cb(resp); }, {Get});
    app().registerHandler("/echo", [](const HttpRequestPtr& req, std::function<void(const HttpResponsePtr&)>&& cb){ auto json=req->getJsonObject(); auto resp=HttpResponse::newHttpJsonResponse(json?*json:Json::Value(Json::objectValue)); cb(resp); }, {Post});
    app().registerHandler("/search", [](const HttpRequestPtr& req, std::function<void(const HttpResponsePtr&)>&& cb){ auto q=req->getParameter("q"); Json::Value j; j["q"]=q; auto resp=HttpResponse::newHttpJsonResponse(j); cb(resp); }, {Get});
    app().registerHandler("/json", [](const HttpRequestPtr& req, std::function<void(const HttpResponsePtr&)>&& cb){ Json::Value j; j["message"]="hello"; for(int i=0;i<3000;i++) j["items"].append(i); j["nested"]["a"]="b"; j["nested"]["count"]=3000; auto resp=HttpResponse::newHttpJsonResponse(j); cb(resp); }, {Get});
    app().setLogLevel(trantor::Logger::kWarn);
    app().addListener("127.0.0.1", 5003);
    app().setThreadNum(4);
    app().run();
    return 0;
}
